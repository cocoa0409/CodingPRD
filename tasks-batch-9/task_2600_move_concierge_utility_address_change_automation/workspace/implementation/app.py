"""Move Concierge & Utility/Address Change Automation API.

Flask application factory and error envelope.  All state lives in process
memory (see db.py); nothing is seeded at startup, so every entity in every test
is constructed through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    clock,
    config,
    consents,
    filings,
    identity,
    moves,
    orders,
    placements,
)

BLUEPRINTS = (
    config.bp,
    moves.bp,
    identity.bp,
    orders.bp,
    filings.bp,
    consents.bp,
    placements.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "The HTTP method is not allowed for this resource.",
            405,
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.", 422
            )
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
