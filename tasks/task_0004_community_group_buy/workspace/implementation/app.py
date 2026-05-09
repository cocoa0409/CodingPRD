"""Application entry point: Flask app factory + global error handlers + bind."""
import os
import threading

from flask import Flask, request

from envelope import error
from errors import APIError, HTTP_BY_ERROR, ERR_VALIDATION_FAILED
from routes import register_routes
from store import store


_request_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _acquire_lock():
        # Serialise all mutations through a global lock to enforce concurrency rules
        _request_lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        try:
            _request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Catch-all for unmatched routes
        return error("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error("ERR_INTERNAL", 500, repr(e))

    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
