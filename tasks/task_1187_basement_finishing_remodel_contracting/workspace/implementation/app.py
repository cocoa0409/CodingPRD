"""Entry point: Flask app, error handlers, route registration.

Boots from a fresh process with an empty in-memory store (no seeding) and the
logical clock at 2026-05-01T00:00:00Z. Listens on $PORT (default 10000),
bound to 0.0.0.0, in the foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import err
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.message, e.http_status)
        app.logger.exception("unexpected error")
        return err("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
