"""Rent-To-Own Store API — Flask application entry point.

Storage is in-memory and starts completely empty on every boot: no entity data
is seeded, preloaded or hardcoded anywhere in this process.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    agreements,
    collections,
    customers,
    delivery,
    payments,
    payoff,
    returns,
    service,
    state_rules,
    stores,
    system,
)

BLUEPRINTS = (
    system.bp,
    state_rules.bp,
    stores.bp,
    customers.bp,
    agreements.bp,
    payments.bp,
    delivery.bp,
    service.bp,
    returns.bp,
    payoff.bp,
    collections.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if status == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST",
                "The method is not allowed for this resource.",
                405,
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", error.description or "Request failed.", status
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - safety net
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 400
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
