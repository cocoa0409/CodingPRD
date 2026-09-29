"""Foodservice National Account Contract & Deviated Pricing API.

A single Flask process with pure in-memory dict storage. Nothing is seeded,
preloaded or persisted: every boot starts from an entirely empty store with the
logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from errors import ApiError
from routes import (
    billback, contracts, deviations, disputes, notices, order_lines, rebates, reference,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (reference, contracts, deviations, notices, rebates,
                   order_lines, billback, disputes):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error(errors.ERR_INVALID_REQUEST,
                                  "No such route.", 404)
        if exc.code == 405:
            return response.error(errors.ERR_INVALID_REQUEST,
                                  "Method not allowed for this route.", 405)
        if exc.code and 400 <= exc.code < 500:
            return response.error(errors.ERR_INVALID_REQUEST,
                                  exc.description or "Malformed request.", exc.code)
        return response.error("ERR_INTERNAL", exc.description or "Internal error.",
                             exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
