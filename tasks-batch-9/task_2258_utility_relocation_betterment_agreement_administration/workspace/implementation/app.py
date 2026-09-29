"""Utility Relocation and Betterment Agreement Administration API.

A single Flask process with a purely in-memory store: every launch starts with an
empty dataset and a logical clock reading exactly 2026-08-01T00:00:00Z.  Nothing
is written to disk and nothing is ever seeded.
"""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError                      # noqa: E402
from response import error                       # noqa: E402
from routes.admin import bp as admin_bp          # noqa: E402
from routes.agreements import bp as agreements_bp  # noqa: E402
from routes.conflicts import bp as conflicts_bp  # noqa: E402
from routes.plans import bp as plans_bp          # noqa: E402
from routes.reads import bp as reads_bp          # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(reads_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(conflicts_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(agreements_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error("ERR_METHOD_NOT_ALLOWED",
                     "The HTTP method is not allowed for this resource.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request payload is malformed.", 400)
        return error("ERR_HTTP_ERROR", exc.description or "HTTP error.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return _http_error(exc)
        app.logger.exception("unhandled error: %s", exc)
        return error("ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
