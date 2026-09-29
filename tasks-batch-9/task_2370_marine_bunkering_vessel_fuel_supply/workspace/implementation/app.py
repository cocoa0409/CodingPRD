"""Marine Bunkering & Vessel Fuel Supply API.

Storage is in-memory only and starts completely empty on every boot: no entity
data is ever seeded, preloaded, registered or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import DEFAULT_MESSAGES, ERROR_STATUS, ApiError
from response import error as error_response
from routes import (
    assets,
    claims,
    customers,
    invoices,
    nominations,
    notes,
    orders,
    reference,
    spills,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        reference,
        customers,
        assets,
        nominations,
        orders,
        notes,
        claims,
        invoices,
        spills,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif status == 415:
            error_id = "ERR_INVALID_REQUEST"
            status = 422
        else:
            error_id = "ERR_INVALID_REQUEST"
            if status < 400:
                status = 400
        message = exc.description or DEFAULT_MESSAGES.get(error_id, "Request failed.")
        return error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response(
            "ERR_INTERNAL", "An unexpected server error occurred: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
