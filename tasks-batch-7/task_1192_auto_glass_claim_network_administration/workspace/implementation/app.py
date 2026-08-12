"""Auto Glass Claim Network API — Flask entry point."""

import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_routes

_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_routes(app)

    @app.before_request
    def _acquire_lock():
        _lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            _lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_exception(err):
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
