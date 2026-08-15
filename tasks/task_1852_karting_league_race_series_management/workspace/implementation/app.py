"""Karting League & Race Series Management API — Flask entry point.

Mounted under /karting. In-memory store; the process boots empty every time
(per-test-server isolation: start.sh is re-invoked before every test).
"""
import os
import threading

from flask import Flask, request

from errors import ApiError
from response import error_response

# Serialize non-GET requests so check-then-act sequences (OCC, capacity
# counts, cascades) behave deterministically under concurrent traffic.
WRITE_LOCK = threading.Lock()


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (
        seasons, drivers, karts, events, entries, sessions, incidents, bookings,
    )
    for mod in (
        seasons, drivers, karts, events, entries, sessions, incidents, bookings,
    ):
        app.register_blueprint(mod.bp, url_prefix="/karting")

    @app.before_request
    def _serialize_writes():
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            WRITE_LOCK.acquire()

    @app.teardown_request
    def _release_writes(exc):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            try:
                WRITE_LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", f"unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
