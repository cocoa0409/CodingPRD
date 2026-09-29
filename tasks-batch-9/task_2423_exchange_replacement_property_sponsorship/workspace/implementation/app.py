"""DST exchange / replacement-property sponsorship API.

Boots clean on every invocation: all state lives in module-level dicts that
start empty, nothing is seeded and nothing touches the filesystem.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ERROR_HTTP, ApiError
from response import error_response
from routes import (
    capital_needs, clock_routes, distributions, exchange_files, exits,
    identifications, investors, leases, ledger, loans, offerings, properties,
    subscriptions, tax_statements, trusts,
)

BLUEPRINTS = (
    clock_routes.bp,
    properties.bp,
    trusts.bp,
    offerings.bp,
    investors.bp,
    exchange_files.bp,
    identifications.bp,
    subscriptions.bp,
    loans.bp,
    leases.bp,
    ledger.bp,
    capital_needs.bp,
    distributions.bp,
    tax_statements.bp,
    exits.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
            message = "The requested resource does not exist."
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "The method is not allowed for this resource."
        elif exc.code == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = "The request is malformed or violates a field constraint."
        else:
            error_id = "ERR_INTERNAL"
            message = exc.description or "Request failed."
        return error_response(error_id, message,
                              exc.code or ERROR_HTTP.get(error_id, 500))

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
