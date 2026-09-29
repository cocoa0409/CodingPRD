"""Bank-Owned Life Insurance & Benefit Plan Funding API.

Flask application factory and process entry point. All state lives in memory
(see store.py) and is empty on every boot: nothing is seeded or persisted to
disk, so a fresh process always starts from a blank platform.
"""

import os
from datetime import datetime
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import ALL_BLUEPRINTS
from util import format_datetime


class ApiJSONProvider(DefaultJSONProvider):
    """Decimals render as JSON numbers, datetimes as ISO 8601 UTC with
    exactly three fractional digits (PRD 2.4, 2.6)."""

    sort_keys = False

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return format_datetime(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = ApiJSONProvider(app)
    app.url_map.strict_slashes = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_RECORD_NOT_FOUND", "Resource not found.", 404)
        if status == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this resource.", 405
            )
        if status in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request payload or query parameters are invalid.", 400
            )
        if status == 401:
            return error_response("ERR_UNAUTHENTICATED", "Authentication is required.", 401)
        if status == 403:
            return error_response("ERR_UNAUTHORIZED", "The acting role is not authorized.", 403)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
