"""Port management utilities: kill processes on a port, extract port from URL."""

import socket
import subprocess
import sys
from urllib.parse import urlparse


def extract_port_from_url(url: str) -> int:
    """Extract port number from a URL. Defaults to 3000 if not specified."""
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return 3000


def is_port_in_use(port: int) -> bool:
    """Check if a port is currently in use via socket connect."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def kill_port(port: int) -> None:
    """
    Kill any process listening on the given TCP port.
    Tries lsof first, falls back to fuser, then ss+kill.
    Swallows errors — best-effort cleanup.
    """
    commands = [
        # Linux/macOS with lsof
        f"lsof -ti:{port} | xargs kill -9 2>/dev/null || true",
        # Linux with fuser
        f"fuser -k {port}/tcp 2>/dev/null || true",
    ]

    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, timeout=5, capture_output=True)
            if not is_port_in_use(port):
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
