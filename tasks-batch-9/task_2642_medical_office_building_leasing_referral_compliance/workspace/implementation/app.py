"""Medical Office Building Leasing & Referral Compliance API.

State lives entirely in process memory (see db.py) and nothing is seeded: a
fresh process starts with every collection empty and the logical clock at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, DEFAULT_MESSAGE, ERROR_STATUS
from response import error_response
from routes import (
    appraisals,
    buildings,
    cases,
    invoices,
    leases,
    ops,
    parking,
    space,
    tenants,
    ti,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        buildings,
        tenants,
        leases,
        appraisals,
        ti,
        invoices,
        cases,
        space,
        parking,
        ops,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND",
                DEFAULT_MESSAGE.get("ERR_RESOURCE_NOT_FOUND", "Resource not found."),
                404,
            )
        if exc.code == 405:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND",
                "The requested method is not allowed on this path.",
                404,
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        status = exc.code or 500
        return error_response(
            "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL",
            exc.description or "Request failed.",
            status,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
