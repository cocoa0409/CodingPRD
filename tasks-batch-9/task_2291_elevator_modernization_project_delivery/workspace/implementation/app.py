"""Elevator Modernization Delivery API — in-memory Flask implementation."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.closeout import bp as closeout_bp
from routes.core import bp as core_bp
from routes.delivery import bp as delivery_bp
from routes.scoping import bp as scoping_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(core_bp)
    app.register_blueprint(scoping_bp)
    app.register_blueprint(delivery_bp)
    app.register_blueprint(closeout_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_NOT_FOUND", "The requested method is not available on this path.", 404
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
