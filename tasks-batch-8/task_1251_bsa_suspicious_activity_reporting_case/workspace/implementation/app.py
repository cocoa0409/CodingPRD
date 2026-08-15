"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

import response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return response.error("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_internal(_err):
        return response.error("ERR_INVALID_REQUEST", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
