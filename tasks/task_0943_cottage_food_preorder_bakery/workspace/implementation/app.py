"""Entry point.

G3 -- EADDRINUSE-tolerant boot.  The harness runs
`prd-bench-local-run --isolation per-test-server`, which kills and relaunches
this process before every single test; the dying process's LISTEN socket can
still hold the port when we come up.  So the listening socket is pre-bound HERE,
with SO_REUSEADDR, inside a BOUNDED retry loop -- 24 attempts x 0.25 s, a
6-second ceiling, then a hard sys.exit(1).  The ceiling is deliberately shorter
than the runner's readiness budget, the loop is never unbounded, and the process
never outlives its parent to squat the port.  The already-bound socket is then
handed to werkzeug via make_server(..., fd=sock.fileno()).

G4 -- storage is plain in-memory dicts.  Nothing is seeded at startup: the store
is empty and every entity a test needs is built through the declared endpoints.
"""

import os
import socket
import sys
import time

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

BIND_ATTEMPTS = 24
BIND_DELAY_SECONDS = 0.25


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (admin, bakers, batches, delivery, handoff, lots,
                        menu_items, orders, payments, recipes, reviews,
                        subscriptions, windows)

    for module in (bakers, recipes, lots, menu_items, windows, orders, handoff,
                   batches, subscriptions, payments, delivery, reviews, admin):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_RESOURCE_NOT_FOUND",
                                  "No such route.")), 404

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return jsonify(error_body("ERR_RESOURCE_NOT_FOUND",
                                  "Method not allowed on this route.")), 404

    @app.errorhandler(400)
    def _bad_request(_exc):
        return jsonify(error_body("ERR_VALIDATION",
                                  "The request is malformed.")), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        if isinstance(exc, ApiError):
            return _api_error(exc)
        return jsonify(error_body("ERR_VALIDATION", str(exc))), 400

    return app


app = create_app()


def _bind(port):
    """Pre-bind the listening socket, tolerating a dying predecessor."""
    last = None
    for _attempt in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(128)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(BIND_DELAY_SECONDS)
    sys.stderr.write("could not bind 0.0.0.0:%d within %.1fs: %s\n"
                     % (port, BIND_ATTEMPTS * BIND_DELAY_SECONDS, last))
    sys.stderr.flush()
    sys.exit(1)


def main():
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(port)
    from werkzeug.serving import make_server
    server = make_server("0.0.0.0", port, app, threaded=True,
                         fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
