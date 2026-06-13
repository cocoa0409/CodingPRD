"""Tattoo & Piercing Studio API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding,
no preloaded entities, no disk persistence. Each fresh process is a clean slate.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.artists import bp as artists_bp
from routes.clients import bp as clients_bp
from routes.chairs import bp as chairs_bp
from routes.flash import bp as flash_bp
from routes.custom_requests import bp as custom_requests_bp
from routes.appointments import bp as appointments_bp
from routes.touchups import bp as touchups_bp
from routes.portfolio import bp as portfolio_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(artists_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(chairs_bp)
    app.register_blueprint(flash_bp)
    app.register_blueprint(custom_requests_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(touchups_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
