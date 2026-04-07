"""Container readiness polling."""

import time

import requests
from loguru import logger

from .config import RunConfig
from .docker_ops import DockerOperations
from .errors import ImplStartupError, ImplStartupTimeout


class HealthChecker:
    def __init__(self, config: RunConfig, docker_ops: DockerOperations):
        self.config = config
        self.docker_ops = docker_ops
        self.poll_interval = 1.0
        self.request_timeout = 2.0

    def wait_until_ready(self, container) -> None:
        """Poll the implementation container until it responds to HTTP.

        Uses the host-mapped port to send GET requests from the runner process.
        """
        port = self.config.port
        timeout = self.config.startup_timeout
        start = time.monotonic()

        # Wait briefly for port mapping to be available
        time.sleep(0.5)

        host_port = self.docker_ops.get_mapped_port(container, port)
        if host_port is None:
            raise ImplStartupError(
                f"No host port mapping found for container port {port}. "
                "Ensure the implementation Dockerfile EXPOSEs the port."
            )

        url = f"http://localhost:{host_port}"
        logger.info(f"Polling {url} for readiness (timeout={timeout}s)...")

        while time.monotonic() - start < timeout:
            # Check if container died
            container.reload()
            if container.status in ("exited", "dead"):
                logs = self.docker_ops.get_container_logs(container)
                raise ImplStartupError(
                    f"Implementation container exited during startup "
                    f"(status={container.status}).\nLogs:\n{logs[-2000:]}"
                )

            try:
                resp = requests.get(url, timeout=self.request_timeout)
                elapsed = time.monotonic() - start
                logger.info(f"Implementation ready (HTTP {resp.status_code}) after {elapsed:.1f}s")
                return
            except (requests.ConnectionError, requests.Timeout):
                pass

            time.sleep(self.poll_interval)

        # Timeout reached
        logs = self.docker_ops.get_container_logs(container)
        raise ImplStartupTimeout(
            f"Implementation did not become ready within {timeout}s.\n"
            f"Logs:\n{logs[-2000:]}"
        )
