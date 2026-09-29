"""Environmental Justice Screening & Permit Review API.

Flask application factory and entry point.  All state lives in process memory
(see db.py); nothing is written to disk and nothing is seeded at startup, so a
fresh process always starts with every collection empty and the logical clock at
2026-08-01T00:00:00Z.
"""
import os
from datetime import date, datetime
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (applications, assessments, complaints, conditions,
                    participation, reference)


class ApiJSONProvider(DefaultJSONProvider):
    """Emit Decimals as JSON numbers and dates as ISO 8601 strings."""

    sort_keys = False

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__)
    app.json_provider_class = ApiJSONProvider
    app.json = ApiJSONProvider(app)
    app.url_map.strict_slashes = False

    for module in (reference, applications, assessments, participation,
                   conditions, complaints):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed for this resource.",
                405,
            )
        if exc.code and exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        return error_response("ERR_INTERNAL", exc.description or "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False,
            use_reloader=False)
