"""Artist Residency Programme Administration -- Flask application factory.

Storage is process-local and in-memory only (see store.py).  Nothing is ever
seeded: every entity in the system is created through the declared endpoints,
so a freshly booted process answers every list endpoint with an empty array.
"""

import os
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

import routes_applications
import routes_cycles
import routes_facilities
import routes_panel
import routes_residencies
import routes_visa_finance
from envelope import error_response
from errors import ApiError


class _JSONProvider(DefaultJSONProvider):
    """Money and percentages are carried as Decimal; emit them as JSON numbers."""

    sort_keys = False

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__)
    app.json = _JSONProvider(app)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_cycles.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_panel.bp)
    app.register_blueprint(routes_residencies.bp)
    app.register_blueprint(routes_facilities.bp)
    app.register_blueprint(routes_visa_finance.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        status = exc.code or 500
        if status in (404, 405):
            return error_response("ERR_NOT_FOUND", "no such endpoint", 404)
        if status == 400:
            return error_response("ERR_VALIDATION", "malformed request", 400)
        return error_response("ERR_VALIDATION", exc.description or "request failed",
                              status)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_VALIDATION", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
