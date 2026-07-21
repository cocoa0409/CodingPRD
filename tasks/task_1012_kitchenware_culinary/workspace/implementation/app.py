"""Kitchenware & Culinary Store API — application entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from envelope import error as error_response
from routes import register


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        # Map framework-level failures (e.g. bad routing) to the envelope.
        if e.code == 404:
            return error_response("ERR_VALIDATION", "Resource not found", 404)
        if e.code == 405:
            return error_response("ERR_VALIDATION", "Method not allowed", 405)
        if e.code == 400:
            return error_response("ERR_VALIDATION", "Bad request", 400)
        return error_response("ERR_VALIDATION", e.description or "Error", e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
