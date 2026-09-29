"""Livestock Mandatory Price Reporting API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot; nothing is
seeded. The process is safe to kill and relaunch before every test.
"""

import os
from datetime import datetime
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

import clock
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate
from routes import audits, clock_routes, entities, market_reports, methodology
from routes import penalties, registrations, submissions, windows


class ApiJSONProvider(DefaultJSONProvider):
    """Emits Decimal as a JSON number and datetimes in the program's ISO form."""

    sort_keys = False

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return clock.iso_millis(o)
        return super().default(o)


def create_app():
    app = Flask(__name__)
    app.json = ApiJSONProvider(app)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        authenticate()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return response.error_response(
            ERR_INVALID_REQUEST,
            exc.description or "The request could not be processed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    for module in (
        entities,
        registrations,
        windows,
        submissions,
        market_reports,
        audits,
        penalties,
        methodology,
        clock_routes,
    ):
        app.register_blueprint(module.bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
