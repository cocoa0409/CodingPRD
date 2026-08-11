"""Flask entry point: error handlers, request serialization, route registration."""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize all request handling: the store is in-memory dicts and the
    # workflows are heavily cascaded, so a single global lock keeps every
    # request's read-modify-write atomic.
    lock = threading.RLock()

    @app.before_request
    def _acquire_lock():
        lock.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % err)

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
