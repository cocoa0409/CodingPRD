"""Entry point: Flask app, error handlers, route registration."""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from helpers import error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        wrapped = ApiError("ERR_NOT_FOUND", err.description or "not found", err.code or 404)
        return error_response(wrapped)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        wrapped = ApiError("ERR_INTERNAL", "internal server error", 500)
        return error_response(wrapped)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
