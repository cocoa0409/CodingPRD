"""Contractor Licensing Board API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: no
seeding, no preloading, no persistence of any kind.
"""

import os

from flask import Flask, jsonify

import core
from core import ApiError, error_body
import routes_reference
import routes_applications
import routes_licenses
import routes_coverage
import routes_complaints
import routes_enforcement
import routes_hearings
import routes_fund


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_reference, routes_applications, routes_licenses,
                   routes_coverage, routes_complaints, routes_enforcement,
                   routes_hearings, routes_fund):
        app.register_blueprint(module.bp)

    @app.before_request
    def _begin():
        core.tx_begin()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_body("ERR_INVALID_REQUEST", "no such route", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_body("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_body("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.message, exc.http_status)
        return error_body("ERR_INVALID_REQUEST", "unprocessable request: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
