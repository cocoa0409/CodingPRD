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
import socket
import subprocess
import sys
import time

import pytest
import requests
from loguru import logger

from ._dnsboot import inject as _inject_dnsboot
from .port_utils import kill_port

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
    # Delegate to the shared implementation in port_utils, which filters
    # strictly to TCP LISTEN sockets (without that filter, lsof also returns
    # PIDs holding client-side connections to localhost:<port>, which on
    # keep-alive HTTP servers (Node/Express, FastAPI, etc.) includes this very
    # pytest process, and `kill -9` on that list would SIGKILL pytest itself
    # between tests).
    #
    # This used to be a private copy that called `lsof` with timeout=5 and did
    # NOT catch subprocess.TimeoutExpired. On a loaded host lsof routinely
    # takes longer than 5s to walk /proc, so the exception escaped
    # pytest_runtest_setup and turned an otherwise-healthy test into
    # "failed on setup with subprocess.TimeoutExpired: ... lsof ...". The
    # shared helper both swallows that timeout and falls back to `ss -H -ltnp`,
    # which is far cheaper than lsof under contention.
    kill_port(port)


def _port_free(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return False
    except OSError:
        return True


def _ensure_port_free(port: int, attempts: int = 30, pause: float = 0.5) -> bool:
    """Kill whatever listens on `port` and confirm the listener is really gone.

    Returns True as soon as the port is observed free. SIGKILL teardown is
    asynchronous and `kill_port` is best-effort (its lsof probe can time out
    under load), so a single shot is not enough: re-issue it each round.
    """
    for _ in range(attempts):
        if _port_free(port):
            return True
        _kill_port(port)
        time.sleep(pause)
    return _port_free(port)


def _spawn_server(port: int, cwd: str, command: str, log_path: str):
    """Spawn one server subprocess (detached, output to log) and return the
    Popen handle so the poll loop can detect an instant crash (e.g.
    EADDRINUSE) and respawn instead of polling a dead process forever."""
    env = _inject_dnsboot({**os.environ, "PORT": str(port)})
    log = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    except OSError:
        log.close()
        return None
    # Child holds its own dup of the fd; close the parent's copy so a long
    # per-test-server run doesn't leak one fd per restart.
    log.close()
    return proc


def _restart_server() -> bool:
    """
    Emergency restart from within the pytest process.
    Spawns a new server subprocess and polls until ready.
    The subprocess is detached so it outlives any single test.
    """
    if not _start_command:
        return False

    port = _extract_port(_api_url)

    # The old listener MUST be gone before we spawn, and observing that is not
    # optional book-keeping — it is what makes the readiness probe below
    # meaningful. The probe is a plain GET against the port, so it cannot tell
    # "my new server is up" from "the previous test's server never died". If we
    # spawn while the old process still holds the port, the new one dies on
    # EADDRINUSE, the very first GET succeeds against the *survivor*, and
    # _restart_server reports success while the suite silently keeps the
    # previous test's in-memory state — which shows up much later as a bogus
    # duplicate-key / wrong-state failure in an unrelated test's setup.
    #
    # So: re-issue the kill until the port actually frees, and fail loudly
    # rather than proceed with a listener we did not start. kill -9 delivery
    # plus socket teardown can take well over 2s on a loaded host, hence the
    # generous budget and the repeated kill rather than a single shot.
    if not _ensure_port_free(port):
        logger.warning(
            f"Port {port} still has a listener after repeated kill attempts; "
            f"refusing to spawn a second server on it (a stale server would "
            f"serve the previous test's state)."
        )
        return False

    directory, command = _parse_command(_start_command)
    cwd = os.path.abspath(directory)
    log_path = os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        f"prd_bench_server_{port}.log",
    )

    # Poll for up to ~30 seconds (60 x 0.5s; nominal — a slow GET can stretch
    # each iteration). The window is generous because the concurrent stability
    # sweep runs 8+ suites in lockstep on shared hosts, where a transient
    # CPU/IO stall can starve an otherwise-healthy boot past a shorter window
    # and surface as a spurious "could not be restarted". Both knobs are
    # env-overridable; a genuinely dead server still fails the poll.
    iters = int(os.environ.get("_PRD_BENCH_RESTART_POLL_ITERS", "60"))
    req_timeout = float(os.environ.get("_PRD_BENCH_RESTART_POLL_TIMEOUT", "1.0"))
    proc = _spawn_server(port, cwd, command, log_path)
    if proc is None:
        return False
    respawns = 0
    for _ in range(iters):
        # Instant-crash detection (e.g. bind failure): respawn instead of
        # burning the whole poll window on a process that will never serve.
        if proc.poll() is not None:
            if respawns >= 3:
                logger.warning(
                    f"Server on port {port} exited immediately "
                    f"(code={proc.returncode}); giving up after {respawns} respawns. "
                    f"See {log_path}"
                )
                return False
            respawns += 1
            logger.info(
                f"Server on port {port} exited immediately "
                f"(code={proc.returncode}), respawning ({respawns}/3). See {log_path}"
            )
            # Same reasoning as before the first spawn: never rebind while a
            # listener survives, or the readiness GET will pass against it.
            if not _ensure_port_free(port, attempts=10, pause=0.2):
                return False
            proc = _spawn_server(port, cwd, command, log_path)
            if proc is None:
                return False
        time.sleep(0.5)
        try:
            requests.get(_api_url, timeout=req_timeout)
            return True
        except (requests.ConnectionError, requests.Timeout):
            continue
    logger.warning(
        f"Server on port {port} did not respond within the restart poll "
        f"window ({iters} iters). See {log_path}"
    )
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
