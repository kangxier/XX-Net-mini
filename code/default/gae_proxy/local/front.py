import os

import xlog
logger = xlog.getLogger("gae_proxy")
logger.set_buffer(500)

from . import check_local_network

from config import config
from . import host_manager
from front_base.openssl_wrap import SSLContext
from front_base.connect_creator import ConnectCreator
from front_base.ip_manager import IpManager
from front_base.ip_source import Ipv4RangeSource, Ipv6PoolSource, IpCombineSource
from front_base.http_dispatcher import HttpsDispatcher
from front_base.connect_manager import ConnectManager
# from .check_ip import CheckIp

from .appid_manager import AppidManager


class Front(object):
    name = "gae_front"

    def __init__(self):
        self.logger = logger
        self.config = config

    def start(self):
        self.running = True

        ca_certs = 'cacert.pem'
        self.openssl_context = SSLContext(
            logger, ca_certs=ca_certs, support_http2=config.support_http2,
            protocol="TLSv1_2"
            #cipher_suites=[b'ALL', b"!RC4-SHA", b"!ECDHE-RSA-RC4-SHA", b"!ECDHE-RSA-AES128-GCM-SHA256",
            #               b"!AES128-GCM-SHA256", b"!ECDHE-RSA-AES128-SHA", b"!AES128-SHA"]
        )

        self.appid_manager = AppidManager(self.config, logger)

        self.host_manager = host_manager.HostManager(self.config, logger)
        self.host_manager.appid_manager = self.appid_manager

        self.connect_creator = ConnectCreator(
            logger, self.config, self.openssl_context, self.host_manager)

        # self.ip_checker = CheckIp(xlog.null, self.config, self.connect_creator)

        self.ip_manager = IpManager(
            logger, self.config,  check_local_network,
            None,
            'good_ip.txt',
            scan_ip_log=None)

        # self.appid_manager.check_api = self.ip_checker.check_ip
        self.appid_manager.ip_manager = self.ip_manager

        self.connect_manager = ConnectManager(
            logger, self.config, self.connect_creator, self.ip_manager, check_local_network)

        self.http_dispatcher = HttpsDispatcher(
            logger, self.config, self.ip_manager, self.connect_manager
        )


    def get_dispatcher(self):
        return self.http_dispatcher

    def request(self, method, host, path=b"/", headers={}, data="", timeout=120):
        response = self.http_dispatcher.request(method, host, path, dict(headers), data, timeout=timeout)

        return response

    def stop(self):
        logger.info("terminate")
        self.connect_manager.set_ssl_created_cb(None)
        self.http_dispatcher.stop()
        self.connect_manager.stop()
        self.ip_manager.stop()

        self.running = False

    def set_proxy(self, args):
        logger.info("set_proxy:%s", args)

        self.config.PROXY_ENABLE = args["enable"]
        self.config.PROXY_TYPE = args["type"]
        self.config.PROXY_HOST = args["host"]
        self.config.PROXY_PORT = args["port"]
        self.config.PROXY_USER = args["user"]
        self.config.PROXY_PASSWD = args["passwd"]

        self.config.save()

        self.connect_creator.update_config()


front = Front()


class DirectFront(object):
    name = "direct_front"

    def __init__(self):
        pass

    def start(self):
        self.running = True

        self.host_manager = host_manager.HostManager(front.config, logger)

        ca_certs = 'cacert.pem'
        self.openssl_context = SSLContext(
            logger, ca_certs=ca_certs, support_http2=False, protocol="TLSv1_2"
        )

        self.connect_creator = ConnectCreator(
            logger, front.config, self.openssl_context, self.host_manager)

        self.ip_manager = front.ip_manager
        self.connect_manager = ConnectManager(
            logger, front.config, self.connect_creator, self.ip_manager, check_local_network)

        self.dispatchs = {}

    def get_dispatcher(self, host):
        if host not in self.dispatchs:
            http_dispatcher = HttpsDispatcher(
                logger, config, front.ip_manager, self.connect_manager)
            self.dispatchs[host] = http_dispatcher

        return self.dispatchs[host]

    def request(self, method, host, path="/", headers={}, data="", timeout=60):
        dispatcher = self.get_dispatcher(host)

        response = dispatcher.request(method, host, path, dict(headers), data, timeout=timeout)

        return response

    def stop(self):
        logger.info("terminate")
        self.connect_manager.set_ssl_created_cb(None)
        for host in self.dispatchs:
            dispatcher = self.dispatchs[host]
            dispatcher.stop()
        self.connect_manager.stop()

        self.running = False

    def set_proxy(self, args):
        self.connect_creator.update_config()

direct_front = DirectFront()
