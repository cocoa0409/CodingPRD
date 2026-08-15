#!/usr/bin/env python3
"""Preflight launcher: bind $PORT before importing the application.

Why this exists: the benchmark runner claims ports from the kernel ephemeral
range (bind to port 0, close, record). On a busy shared host the same range
supplies source ports for outbound localhost connections, so a claimed port
can be transiently occupied by a client-side TIME_WAIT (up to ~30s) whose
original socket lacked SO_REUSEADDR — a state a later bind() cannot override
even with SO_REUSEADDR. The previous entry point paid a ~1s Flask import
*before* binding, leaving a wide claimed-but-unbound window on every per-test
restart; under the 8-round concurrent sweep that window was hit repeatedly
and surfaced as spurious "could not be restarted" setup errors.

Binding here — in a minimal interpreter, before any heavy import — shrinks
that window to milliseconds, and the retry loop rides out any stale TIME_WAIT
still inside the runner's 15s restart-poll window. The bound fd is handed to
app.py via WERKZEUG_BIND_FD (werkzeug make_server accepts fd=...), so the
port is never unbound between claim and serve.
"""
import os
import socket
import subprocess
import sys
import time

PORT = int(os.environ.get("PORT", "10000"))


def main():
    # 1. Bind the listen socket immediately, retrying over transient
    #    EADDRINUSE (stale client-side TIME_WAIT on the claimed port).
    deadline = time.monotonic() + 13.0
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", PORT))
            sock.listen(128)
            break
        except OSError:
            sock.close()
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    sock.set_inheritable(True)
    os.environ["WERKZEUG_BIND_FD"] = str(sock.fileno())

    # 2. Ensure dependencies (no-op when already installed).
    try:
        import flask  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"]
        )

    # 3. Exec the app on the pre-bound socket (same PID, fd survives exec).
    os.execvp(sys.executable, [sys.executable, "app.py"])


if __name__ == "__main__":
    main()
