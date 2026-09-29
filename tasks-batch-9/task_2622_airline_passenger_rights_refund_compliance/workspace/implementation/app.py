"""Airline Passenger Rights & Refund Compliance API entry point.

Storage is in-memory only and starts completely empty on every boot: no seeding,
no preloading, no file or SQLite persistence anywhere.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError

import routes_complaints
import routes_core
import routes_denied
import routes_extras
import routes_obligations
import routes_reports
import routes_segments
import routes_tarmac


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_core,
        routes_segments,
        routes_extras,
        routes_denied,
        routes_tarmac,
        routes_obligations,
        routes_complaints,
        routes_reports,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405)
        if exc.code and exc.code < 500:
            return error("ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400)
        return error("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
