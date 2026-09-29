"""Project-Based Rental Assistance Contract Renewal API.

Flask application factory. All state lives in the in-memory dictionaries of
`core.DB`; nothing is persisted and nothing is seeded, so every boot starts
from an empty store with the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from core import ApiError, authenticate, respond_error
import routes_money
import routes_portfolio
import routes_renewal
import routes_restructuring
import routes_studies
import routes_tenants
import routes_ua

API_PREFIX = "/pbra"

BLUEPRINT_MODULES = (
    routes_portfolio,
    routes_renewal,
    routes_studies,
    routes_ua,
    routes_tenants,
    routes_restructuring,
    routes_money,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in BLUEPRINT_MODULES:
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _authenticate():
        # Ladder step 1 runs for every matched route; an unmatched URL is a
        # routing problem and must not be reported as an auth failure.
        if request.method == "OPTIONS" or request.url_rule is None:
            return None
        authenticate()
        return None

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return respond_error("ERR_INVALID_REQUEST",
                             "The request could not be understood.", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return respond_error("ERR_INVALID_REQUEST",
                             "No route matches this path.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return respond_error("ERR_INVALID_REQUEST",
                             "This method is not allowed on this path.", 405)

    @app.errorhandler(415)
    def _unsupported_media(exc):
        return respond_error("ERR_INVALID_REQUEST",
                             "Request body must be JSON.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return respond_error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return respond_error("ERR_INVALID_REQUEST",
                                 exc.description or "Request rejected.",
                                 exc.code or 400)
        app.logger.exception("unhandled error")
        return respond_error("ERR_INVALID_REQUEST", str(exc) or "Unhandled error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True,
            debug=False,
            use_reloader=False)
