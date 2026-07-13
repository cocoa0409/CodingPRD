"""Entry point for the Extended-Stay & Corporate Housing API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_body
from routes import register


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_body("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_body("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.http_status, exc.message)
        code = exc.code or 500
        if code == 404 or code == 405:
            return error_body("ERR_NOT_FOUND", 404, "Resource not found")
        return error_body("ERR_VALIDATION", 400 if code < 500 else 500, exc.description or "error")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, (ApiError, HTTPException)):
            raise exc
        return error_body("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
