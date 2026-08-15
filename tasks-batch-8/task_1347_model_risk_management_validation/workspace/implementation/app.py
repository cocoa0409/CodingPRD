"""MRM API entry point: Flask app assembly, error handlers, server startup."""
import os

from flask import Flask

from errors import ApiError
from middleware import authenticate
from response import error as error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.before_request(authenticate)
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
