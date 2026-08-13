"""Hose Fittings Hydraulic Counter API.

Flask entry point. In-memory only; the store starts empty on every boot.
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import register_all


def create_app():
    app = Flask(__name__, static_folder=None)
    register_all(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_INVALID_REQUEST, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
