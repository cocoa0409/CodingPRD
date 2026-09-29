"""Regional Airline Capacity Purchase Agreement settlement service.

Flask application factory.  All state lives in process memory (see db.py) and is
empty on every boot; the logical clock always starts at its fixed instant.
"""

import os
from decimal import Decimal

from flask import Flask, g
from flask.json.provider import DefaultJSONProvider

import routes
from core import clock
from db import store
from errors import ApiError
from response import error_response


class ApiJSONProvider(DefaultJSONProvider):
    """Preserve field insertion order and render Decimal money as JSON numbers."""

    sort_keys = False

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = ApiJSONProvider(app)
    app.url_map.strict_slashes = False

    clock.reset()
    store.reset()

    routes.register(app)

    @app.before_request
    def _begin_request():
        g.touched = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Method not allowed for this path", 405)

    @app.errorhandler(400)
    def _handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=False, use_reloader=False)
