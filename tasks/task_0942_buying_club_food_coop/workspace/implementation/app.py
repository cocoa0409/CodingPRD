"""Buying Club & Food Co-op Order Platform API — entry point.

The store is in-memory and starts EMPTY on every boot: nothing is seeded.

Startup order matters here and is deliberate.  Under per-test-server isolation
the harness SIGKILLs the previous server and immediately relaunches this one on
the *same* port, and that port comes from the kernel's ephemeral range
(/proc/sys/net/ipv4/ip_local_port_range, 32768-60999).  Every millisecond
between the predecessor's death and our bind() is a window in which any
unrelated process on the box can pick that exact number as the *source* port of
an outbound connection, which then blocks a wildcard bind for as long as that
connection lives.  So this module imports nothing but the standard library at
top level and claims the listening socket as the very first thing `main` does;
Flask, the blueprints and even the dependency check all happen afterwards, off
the critical path.
"""

import os
import socket
import sys
import time

BIND_ATTEMPTS = 280
BIND_DELAY_SECONDS = 0.05


def bind_listening_socket(port):
    """Bounded pre-bind: 280 attempts x 0.05 s (a 14 s hard ceiling), then exit.

    The ceiling sits just inside the harness's ~15 s readiness budget: retrying
    for less turns a port that would have come free into a hard "could not be
    restarted" error, while retrying past it would leave a winner the harness
    has already given up on.  The poll is tight so the bind lands within a tick
    of the release.
    """
    for _attempt in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(128)
            return sock
        except OSError:
            sock.close()
            time.sleep(BIND_DELAY_SECONDS)
    sys.stderr.write("could not bind port %d within the pre-bind ceiling\n" % port)
    sys.exit(1)


def ensure_dependencies():
    """Install requirements only when they are actually missing.

    start.sh is re-invoked before every per-test reboot; an unconditional pip
    install would contend hundreds of times and blow the restart window.
    find_spec is far cheaper than importing Flask, and running the check here
    rather than in start.sh keeps a second interpreter spawn out of the
    port-exposure window described in the module docstring.
    """
    import importlib.util
    if importlib.util.find_spec("flask") is not None:
        return
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    os.path.join(here, "requirements.txt")], check=False)


def create_app():
    from flask import Flask
    from werkzeug.exceptions import HTTPException

    from core.envelope import error
    from core.errors import ERROR_HTTP, ApiError
    from routes import (r_catalog, r_commission, r_credits, r_cycles,
                        r_dropruns, r_lines, r_members, r_orders, r_payments,
                        r_recon, r_receiving, r_routeruns, r_volunteers)

    blueprints = (
        r_catalog.bp, r_members.bp, r_cycles.bp, r_routeruns.bp, r_dropruns.bp,
        r_orders.bp, r_lines.bp, r_receiving.bp, r_payments.bp, r_recon.bp,
        r_commission.bp, r_volunteers.bp, r_credits.bp,
    )

    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error("ERR_VALIDATION", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error("ERR_VALIDATION", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error("ERR_VALIDATION", exc.description or "Bad request",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    _ = ERROR_HTTP
    return app


def main():
    port = int(os.environ.get("PORT", "10000"))
    sock = bind_listening_socket(port)
    ensure_dependencies()
    app = create_app()
    from werkzeug.serving import make_server
    server = make_server("0.0.0.0", port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
