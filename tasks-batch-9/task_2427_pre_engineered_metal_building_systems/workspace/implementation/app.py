"""Pre-Engineered Metal Building Systems API.

Storage is in-memory only and starts completely empty on every boot: no seed
data, no fixtures, no persistence of any kind. The process encodes the system
(state machines, calculations, validations, endpoints) and nothing else.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ERROR_CATALOG, ApiError
from response import error_response
from routes import (
    builders,
    clock,
    configurations,
    designs,
    drawing_packages,
    jurisdictions,
    orders,
    production,
    quotes,
    shipments,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (
        jurisdictions,
        builders,
        configurations,
        quotes,
        designs,
        drawing_packages,
        orders,
        production,
        shipments,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if status == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed for this resource.", 405
            )
        if status == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body or query string is invalid.", 400
            )
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover -- defensive only
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

# Referenced so the catalogue import is never pruned by a linter.
assert "ERR_UNAUTHENTICATED" in ERROR_CATALOG


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
