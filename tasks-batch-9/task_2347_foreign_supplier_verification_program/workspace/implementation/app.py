"""FSVP compliance API — Flask application entry point.

Storage is entirely in-memory (see db.py); the process starts with an empty
store and a logical clock pinned at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.actions import bp as actions_bp
from routes.activities import bp as activities_bp
from routes.clock import bp as clock_bp
from routes.entries import bp as entries_bp
from routes.hazards import bp as hazards_bp
from routes.importers import bp as importers_bp
from routes.pairs import bp as pairs_bp
from routes.records import bp as records_bp
from routes.suppliers import bp as suppliers_bp

BLUEPRINTS = (
    importers_bp,
    suppliers_bp,
    pairs_bp,
    hazards_bp,
    activities_bp,
    records_bp,
    actions_bp,
    entries_bp,
    clock_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "no such route", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_INVALID_REQUEST", "method not allowed for this route", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if isinstance(exc, ApiError):  # pragma: no cover - defensive
            return error_response(exc.error_id, exc.message, exc.http_status)
        status = exc.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        return error_response(error_id, exc.description or "request failed", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):  # pragma: no cover - defensive
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
