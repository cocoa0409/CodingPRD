"""Email Marketing Automation API -- entry point.

In-memory only. The store starts EMPTY on every boot: no entity is seeded,
preloaded or hardcoded. Tests build all state through the API surface.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, DEFAULT_MESSAGES
from response import error
from routes import bp

# Every request runs under this lock: the store is shared mutable state and each
# request must observe/commit it atomically (consistency_model: immediate).
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.before_request
    def _acquire():
        _REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            _REQUEST_LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_ACCOUNT_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error("ERR_FORBIDDEN_ROLE", "Method not allowed.", 405)
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST",
                         DEFAULT_MESSAGES["ERR_INVALID_REQUEST"], 400)
        return error("ERR_INVALID_REQUEST", str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        app.logger.exception("unhandled error")
        return error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
