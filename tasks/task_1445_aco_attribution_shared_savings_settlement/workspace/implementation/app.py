"""ACO Shared Savings API -- Flask entry point.

In-memory only: every process boot starts with empty tables (see db.py).
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os
import threading

from flask import Flask

import response
from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_REQUEST
from routes import register_routes

_request_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _acquire_lock():
        # Serialize request handling so in-memory mutations stay atomic.
        _request_lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        _request_lock.release()

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return response.error(ERR_RESOURCE_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return response.error(ERR_INVALID_REQUEST, 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_internal(err):
        return response.error("ERR_INTERNAL", 500, f"Internal error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
