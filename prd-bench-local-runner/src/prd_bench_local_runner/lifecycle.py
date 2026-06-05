"""
Server lifecycle management: start, stop, liveness check, crash recovery.

Handles start, stop, health polling, and crash recovery for the server under test.
"""

import atexit
import os
import re
import signal
import subprocess
import sys
import time
from typing import Optional

import requests
from loguru import logger

from ._dnsboot import inject as _inject_dnsboot
from .port_utils import extract_port_from_url, kill_port


class ServerStartError(Exception):
    pass


class ServerStartTimeout(Exception):
    pass


class ServerLifecycleManager:
    """
    Manages the lifecycle of an API server subprocess.

    Handles:
    - Parsing "cd dir && command" syntax
    - Killing existing processes on the target port
    - Spawning the server subprocess
    - Polling until the server responds to HTTP
    - Graceful shutdown (SIGTERM → SIGKILL fallback)
    - Liveness checks and crash recovery
    """

    def __init__(
        self,
        start_command: str,
        api_url: str = "http://localhost:10000",
        startup_timeout: float = 30.0,
        poll_interval: float = 0.8,
        liveness_timeout: float = 0.5,
    ):
        self.start_command = start_command
        self.api_url = api_url
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval
        self.liveness_timeout = liveness_timeout
        self._process: Optional[subprocess.Popen] = None
        self._port = extract_port_from_url(api_url)
        self._directory, self._actual_command = self._parse_command(start_command)

        # Register cleanup on interpreter exit
        atexit.register(self._atexit_cleanup)

    @staticmethod
    def _parse_command(command: str) -> tuple[str, str]:
        """Parse 'cd dir && actual_command' into (directory, command)."""
        match = re.match(r"cd\s+(\S+)\s*&&\s*(.*)", command)
        if match:
            return match.group(1), match.group(2).strip()
        return ".", command.strip()

    def start(self) -> None:
        """Start the server: kill port → spawn → poll until ready."""
        if self._process and self._process.poll() is None:
            logger.info("Server process already running, skipping start.")
            return

        logger.info(f"Starting server: {self.start_command}")
        logger.info(f"Target: {self.api_url}")

        # Kill any existing process on the port
        kill_port(self._port)

        # Resolve working directory
        cwd = os.path.abspath(self._directory)
        if not os.path.isdir(cwd):
            raise ServerStartError(f"Working directory does not exist: {cwd}")

        # Spawn the server
        env = _inject_dnsboot({**os.environ, "PORT": str(self._port)})
        try:
            self._process = subprocess.Popen(
                self._actual_command,
                shell=True,
                cwd=cwd,
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except OSError as e:
            raise ServerStartError(f"Failed to spawn: {self._actual_command!r} in {cwd}: {e}")

        # Poll until server responds
        self._poll_until_ready(self.startup_timeout)
        logger.info("Server started successfully.")

    def _poll_until_ready(self, timeout: float) -> None:
        """Poll the server URL until it responds to any HTTP request."""
        elapsed = 0.0
        while elapsed < timeout:
            # Check if process died
            if self._process and self._process.poll() is not None:
                code = self._process.returncode
                self._process = None
                raise ServerStartError(
                    f"Server process exited prematurely with code {code}"
                )

            try:
                requests.get(self.api_url, timeout=self.poll_interval - 0.1)
                return  # Any response means the server is up
            except requests.ConnectionError:
                pass  # Server not ready yet
            except requests.Timeout:
                pass  # Server not ready yet
            except Exception as e:
                self._kill_process()
                raise ServerStartError(f"Unexpected error while polling: {e}")

            time.sleep(self.poll_interval)
            elapsed += self.poll_interval

        self._kill_process()
        raise ServerStartTimeout(
            f"Server did not respond at {self.api_url} within {timeout}s"
        )

    def stop(self) -> None:
        """Stop the server: SIGTERM → wait → SIGKILL → kill_port."""
        if not self._process:
            return

        logger.info("Stopping server...")
        pid = self._process.pid

        # Try graceful shutdown
        try:
            self._process.terminate()  # SIGTERM
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning(f"SIGTERM timeout, sending SIGKILL to pid {pid}")
            self._process.kill()  # SIGKILL
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

        self._process = None

        # Safety net: kill anything still on the port
        kill_port(self._port)
        logger.info("Server stopped.")

    def check_liveness(self) -> bool:
        """Return True if the server responds to HTTP."""
        try:
            requests.get(self.api_url, timeout=self.liveness_timeout)
            return True
        except (requests.ConnectionError, requests.Timeout):
            return False

    def ensure_liveness(self) -> None:
        """If server is dead, attempt restart with shorter timeout."""
        if self.check_liveness():
            return
        logger.warning("Server not responding, attempting restart...")
        self.stop()
        self.start.__wrapped__ = True  # avoid recursion guard
        # Re-spawn with shorter timeout
        kill_port(self._port)
        cwd = os.path.abspath(self._directory)
        env = _inject_dnsboot({**os.environ, "PORT": str(self._port)})
        try:
            self._process = subprocess.Popen(
                self._actual_command,
                shell=True,
                cwd=cwd,
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            self._poll_until_ready(15.0)
            logger.info("Server restarted successfully.")
        except (ServerStartError, ServerStartTimeout) as e:
            logger.error(f"Restart failed: {e}")

    def _kill_process(self) -> None:
        """Force-kill the current process."""
        if self._process:
            try:
                self._process.kill()
                self._process.wait(timeout=3)
            except Exception:
                pass
            self._process = None

    def _atexit_cleanup(self) -> None:
        """Cleanup on interpreter exit."""
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
