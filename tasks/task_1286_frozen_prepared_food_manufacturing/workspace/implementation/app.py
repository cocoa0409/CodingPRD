"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected error: %s" % err))

    app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
