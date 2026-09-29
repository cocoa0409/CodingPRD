"""CMBS Special Servicing API — Flask application factory and entry point.

Storage is in-memory only (see db.py) and is completely empty on every boot:
no seeding, no preloading, no persistence of any kind.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes_core import bp as core_bp
from routes_credit import bp as credit_bp
from routes_disposition import bp as disposition_bp
from routes_workout import bp as workout_bp

API_PREFIX = "/special-servicing"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (core_bp, credit_bp, workout_bp, disposition_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "Method not allowed for this route.", 405)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc,
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
