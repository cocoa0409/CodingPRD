"""Contractor Safety Prequalification API — entry point.

The store is in-memory and starts completely empty on every boot: nothing is
seeded, preloaded or hardcoded here or in any imported module.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes_access
import routes_admin
import routes_cure
import routes_docs
import routes_insurance
import routes_prequal
import routes_read
import routes_runs
import routes_sub
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_admin,
        routes_prequal,
        routes_docs,
        routes_insurance,
        routes_access,
        routes_cure,
        routes_sub,
        routes_runs,
        routes_read,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_RECORD_NOT_FOUND", "Resource not found.", 404
            )
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this resource.", 405
            )
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Malformed request.", 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be handled.", exc.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
