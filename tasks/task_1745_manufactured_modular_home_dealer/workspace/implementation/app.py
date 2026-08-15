"""Entry point: Flask app, error handlers, route registration."""

import os
import traceback

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_VALIDATION", "Resource or route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_VALIDATION", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
