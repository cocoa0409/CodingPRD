"""Kids Clothing Rent & Swap Subscription API.

Storage is in-memory only and nothing is ever seeded: every table starts empty
on each boot, so re-invoking start.sh wipes all state.
"""

import os
import socket
import sys
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (boxes, buyouts, capsules, catalog, claims, cycles, grading,
                    ledgers, members, pauses, plans, shipping, swaps, system,
                    tradein)

BLUEPRINTS = [
    system.bp,
    plans.bp,
    members.bp,
    cycles.bp,
    catalog.bp,
    boxes.bp,
    swaps.bp,
    shipping.bp,
    grading.bp,
    tradein.bp,
    ledgers.bp,
    buyouts.bp,
    capsules.bp,
    pauses.bp,
    claims.bp,
]


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope.error_body(error.error_id, error.message), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return envelope.error_body("ERR_RESOURCE_NOT_FOUND", "Unknown route."), 404
        if error.code == 405:
            return envelope.error_body("ERR_ROLE_FORBIDDEN", "Method not allowed."), 405
        if error.code in (400, 415):
            return envelope.error_body("ERR_VALIDATION", "Malformed request."), 422
        return envelope.error_body("ERR_VALIDATION", str(error)), error.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return envelope.error_body("ERR_VALIDATION", "Unexpected server error: %s" % error), 500

    return app


app = create_app()


def _bind(host, port, timeout=12.0):
    """Bounded pre-bind retry: the previous per-test server's LISTEN socket can
    still hold the port when the next process starts. Binding here (instead of
    letting Werkzeug bind) means the bind can never fail underneath the server
    and sys.exit(1) the process."""
    deadline = time.time() + timeout
    delay = 0.02
    last = None
    while True:
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
            if time.time() >= deadline:
                raise last
            time.sleep(delay)
            delay = min(delay * 1.5, 0.2)


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        try:
            server.server_close()
        except Exception:  # pragma: no cover
            pass
        try:
            sock.close()
        except Exception:  # pragma: no cover
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
