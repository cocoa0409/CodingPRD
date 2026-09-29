"""Out-of-District Special Education Placement & Tuition Management API.

All state is held in process memory only. Nothing is seeded at import time -
every entity is created through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_billing
import routes_claims
import routes_decisions
import routes_placements
import routes_progress
import routes_reference
import routes_services
from errors import ERROR_STATUS, ApiError
from response import error

API_PREFIX = "/ood-placements"

DOMAIN_BLUEPRINTS = (
    routes_reference.bp,
    routes_decisions.bp,
    routes_placements.bp,
    routes_services.bp,
    routes_billing.bp,
    routes_claims.bp,
    routes_progress.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.clock_bp)
    for blueprint in DOMAIN_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return error(
            "ERR_METHOD_NOT_ALLOWED",
            "The HTTP method is not allowed for this resource.",
            405,
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        status = exc.code or 500
        if status == 400:
            return error("ERR_INVALID_REQUEST", "The request payload is malformed.", 400)
        return error(
            "ERR_HTTP_ERROR",
            exc.description or "The request could not be processed.",
            status,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error("ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    return app


app = create_app()

# Referenced so linters keep the import; the catalogue must cover every code.
assert isinstance(ERROR_STATUS, dict)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
