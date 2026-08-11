"""Mobile Veterinary Diagnostics & Imaging API — entry point.

Startup is EADDRINUSE-tolerant on purpose: the benchmark harness runs with
`--isolation per-test-server`, killing and relaunching this process before every
single test, so a fresh process routinely races the dying process's LISTEN
socket.  Werkzeug's default behaviour is to sys.exit(1) on bind failure, which
surfaces as a spurious "server could not be restarted" error.  We therefore
create the socket ourselves, set SO_REUSEADDR, and bind in a BOUNDED retry loop
(24 attempts x 0.25s = a 6 second ceiling, comfortably inside the harness's
readiness budget) before giving up hard.  The loop is bounded on purpose: an
unbounded one would leave an orphan squatting the port, which is worse than the
original flake.
"""

import os
import socket
import sys
import time

from flask import Flask, jsonify

from core import envelope
from core.errors import ApiError
from routes.billing import bp as billing_bp
from routes.intake import bp as intake_bp
from routes.reading import bp as reading_bp
from routes.reference import bp as reference_bp
from routes.routing import bp as routing_bp
from routes.studies import bp as studies_bp

BIND_ATTEMPTS = 24
BIND_SLEEP_SECONDS = 0.25


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(routing_bp)
    app.register_blueprint(intake_bp)
    app.register_blueprint(studies_bp)
    app.register_blueprint(reading_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return envelope.error_response(
            "ERR_RECORD_NOT_FOUND", "No such endpoint.", 404
        )

    @app.errorhandler(405)
    def handle_405(_exc):
        return envelope.error_response(
            "ERR_RECORD_NOT_FOUND", "Method not allowed for this path.", 404
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        if isinstance(exc, ApiError):
            return envelope.error_response(exc.error_id, exc.message, exc.http_status)
        return envelope.error_response(
            "ERR_VALIDATION", "Unexpected server error: %s" % exc, 400
        )

    return app


app = create_app()


def _bind_socket(host, port):
    last_error = None
    for _ in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(256)
            return sock
        except OSError as exc:
            last_error = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(BIND_SLEEP_SECONDS)
    sys.stderr.write("failed to bind %s:%s -> %s\n" % (host, port, last_error))
    sys.stderr.flush()
    sys.exit(1)


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind_socket(host, port)

    from werkzeug.serving import make_server

    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
