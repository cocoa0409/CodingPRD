"""Neighborhood Pet-Sitting Cooperative API — Flask entry point.

In-memory store, logical clock defaulting to 2026-08-01T00:00:00Z, no seeding.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_resp
from routes import (
    assignments,
    claims,
    clock_routes,
    disputes,
    entries,
    handoffs,
    holidays,
    incidents,
    ledger,
    members,
    pets,
    references,
    requests,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        clock_routes,
        members,
        references,
        pets,
        holidays,
        requests,
        claims,
        assignments,
        handoffs,
        entries,
        incidents,
        disputes,
        ledger,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_resp(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_resp(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_resp(ApiError(ERR_NOT_FOUND, 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_resp(err)
        return error_resp(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
