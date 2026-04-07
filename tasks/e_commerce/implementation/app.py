"""E-Commerce Marketplace API — entry point."""

import os
from flask import Flask
from errors import AppError
import response as resp


def create_app():
    app = Flask(__name__)

    # Global error handler: convert AppError → response envelope
    @app.errorhandler(AppError)
    def handle_app_error(e):
        return resp.error(e.error_id, e.message, e.http_status)

    # Catch unexpected errors
    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return resp.error("ERR_INTERNAL", str(e), 500)

    # Register all route blueprints
    from routes import register_routes
    register_routes(app)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
