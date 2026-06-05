"""
Pytest plugin: per-test liveness check with crash auto-restart.

Registered via `pytest -p prd_bench_local_runner.pytest_plugin` by the TestExecutor.
Reads configuration from environment variables set by the runner:
  _PRD_BENCH_API_URL          - server URL to check
  _PRD_BENCH_START_COMMAND    - command to restart server if crashed
  _PRD_BENCH_SKIP_LIFECYCLE   - "true" to disable checks
  _PRD_BENCH_ISOLATION        - "per-test-server" to restart before each test

Mirrors the pattern of checking server health before each test to prevent cascade failures.
"""

import os
import re
import subprocess
import sys
import time

import pytest
import requests
from loguru import logger

from ._dnsboot import inject as _inject_dnsboot

_api_url = os.environ.get("_PRD_BENCH_API_URL", "http://localhost:10000")
_start_command = os.environ.get("_PRD_BENCH_START_COMMAND", "")
_skip = os.environ.get("_PRD_BENCH_SKIP_LIFECYCLE", "false") == "true"
_isolation = os.environ.get("_PRD_BENCH_ISOLATION", "none")


def _parse_command(command: str) -> tuple[str, str]:
    match = re.match(r"cd\s+(\S+)\s*&&\s*(.*)", command)
    if match:
        return match.group(1), match.group(2).strip()
    return ".", command.strip()


def _extract_port(url: str) -> int:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.port or 10000


def _kill_port(port: int) -> None:
    # Filter strictly to TCP LISTEN sockets — without this, lsof also returns
    # PIDs holding client-side connections to localhost:<port>, which on
    # keep-alive HTTP servers (Node/Express, FastAPI, etc.) includes this
    # very pytest process. `xargs kill -9` on that list would SIGKILL pytest
    # itself between tests. See port_utils.kill_port for the full rationale.
    subprocess.run(
        f"pids=$(lsof -ti:{port} -sTCP:LISTEN 2>/dev/null); "
        f"[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null; true",
        shell=True, timeout=5, capture_output=True,
    )


def _restart_server() -> bool:
    """
    Emergency restart from within the pytest process.
    Spawns a new server subprocess and polls until ready.
    The subprocess is detached so it outlives any single test.
    """
    if not _start_command:
        return False

    port = _extract_port(_api_url)
    _kill_port(port)

    directory, command = _parse_command(_start_command)
    cwd = os.path.abspath(directory)
    env = _inject_dnsboot({**os.environ, "PORT": str(port)})

    try:
        subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False

    # Poll for up to 15 seconds
    for _ in range(30):
        time.sleep(0.5)
        try:
            requests.get(_api_url, timeout=0.4)
            return True
        except (requests.ConnectionError, requests.Timeout):
            continue
    return False


def pytest_runtest_setup(item):
    """Before each test: check server liveness, restart if needed."""
    if _skip:
        return

    if _isolation == "per-test-server":
        logger.info(f"Restarting API server before {item.nodeid}")
        if _restart_server():
            return
        pytest.fail(
            f"API server at {_api_url} could not be restarted before {item.nodeid}.",
            pytrace=False,
        )

    try:
        requests.get(_api_url, timeout=0.5)
    except (requests.ConnectionError, requests.Timeout):
        # Server is down — attempt restart
        logger.warning(f"Server at {_api_url} not responding, restarting...")
        if _restart_server():
            logger.info("Server restarted successfully.")
        else:
            pytest.fail(
                f"API server at {_api_url} is not responding and restart failed. "
                f"Server may have crashed during previous test.",
                pytrace=False,
            )
