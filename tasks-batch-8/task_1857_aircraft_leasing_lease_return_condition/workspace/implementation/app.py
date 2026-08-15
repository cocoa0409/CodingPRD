"""Aircraft Leasing Returns API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import LOCK
from errors import ApiError
from response import error_envelope
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc):
        try:
            LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_envelope(e.error_id, e.message, e.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(e):
        if e.code == 404:
            return error_envelope("ERR_NOT_FOUND", "Resource not found", 404)
        return error_envelope(
            "ERR_INVALID_REQUEST",
            getattr(e, "description", None) or "Request failed",
            e.code or 500,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        return error_envelope("ERR_INTERNAL", "Internal server error", 500)

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
