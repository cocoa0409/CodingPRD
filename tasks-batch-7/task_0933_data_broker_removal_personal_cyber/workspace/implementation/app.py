"""Entry point: blueprint registration, error handling and the hardened bind.

The harness runs `--isolation per-test-server`, which kills and relaunches this
process before EVERY pytest test. The dying process's LISTEN socket races the
new bind, and Werkzeug `sys.exit(1)`s on bind failure, which the harness reports
as "server could not be restarted". A try/except around `app.run` does not fix
that. Instead the socket is pre-bound here with SO_REUSEADDR inside an
EADDRINUSE-tolerant retry loop, and the server is then handed the ready file
descriptor via `werkzeug.serving.make_server(..., fd=...)`.
"""

import os
import socket
import sys
import time

from flask import Flask, jsonify

import envelope
from errors import ERROR_STATUS, ApiError

BIND_ATTEMPTS = 40
BIND_RETRY_SECONDS = 0.25


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        accounts,
        addons,
        breaches,
        brokers,
        cycles,
        documents,
        exposures,
        findings,
        members,
        plans,
        profiles,
        removals,
        scans,
        seats,
        system,
    )

    for module in (
        system,
        plans,
        accounts,
        members,
        documents,
        profiles,
        brokers,
        scans,
        exposures,
        removals,
        breaches,
        findings,
        addons,
        seats,
        cycles,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return envelope.error("ERR_VALIDATION", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return envelope.error("ERR_VALIDATION", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        import traceback

        traceback.print_exc()
        return envelope.error("ERR_VALIDATION", f"Unexpected server error: {exc}", 500)

    return app


app = create_app()


def bind_socket(host, port):
    """Pre-bind with SO_REUSEADDR, tolerating a dying predecessor's socket."""
    last = None
    for _ in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(256)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(BIND_RETRY_SECONDS)
    raise last


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = bind_socket(host, port)
    from werkzeug.serving import make_server

    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
