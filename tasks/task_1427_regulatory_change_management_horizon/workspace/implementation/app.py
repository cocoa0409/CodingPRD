"""Regulatory Change Management API — Flask entry point.

Boots an in-memory server bound to 0.0.0.0:$PORT (default 10000). The store
starts empty on every boot except the mandated ObligationRegister singleton.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (ApiError, ERR_INTERNAL, ERR_INVALID_REQUEST, ERR_NOT_FOUND)
from response import api_error, error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return api_error(404, ERR_NOT_FOUND, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return api_error(405, ERR_INVALID_REQUEST, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        if isinstance(err, HTTPException):
            return api_error(err.code or 500,
                             ERR_NOT_FOUND if err.code == 404 else ERR_INVALID_REQUEST,
                             err.description or "HTTP error")
        app.logger.exception("unhandled error: %s", err)
        return api_error(500, ERR_INTERNAL, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
