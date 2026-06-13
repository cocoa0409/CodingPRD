"""Appliance & Electronics Trade-In API — Flask entry point.

In-memory storage only; nothing seeded at startup. A fresh process boots with a
completely empty store (required by `--isolation per-test-server`).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

# Import blueprints.
from routes.catalogs import bp as catalogs_bp
from routes.customers import bp as customers_bp
from routes.tradeins import bp as tradeins_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalogs_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(tradeins_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / method -> not found in our envelope.
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected errors as a generic invalid-request rather than HTML.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
