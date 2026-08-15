"""Flask application entry point: error handlers and route registration."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", "The requested path does not exist", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        status = e.code or 500
        error_id = "ERR_VALIDATION" if status == 400 else f"ERR_HTTP_{status}"
        return error_response(error_id, e.description or "HTTP error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", f"Internal server error: {e}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
