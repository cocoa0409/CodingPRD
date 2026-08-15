"""Yacht Brokerage & Vessel Documentation API — Flask entry point.
In-memory only; store starts empty on every boot."""
import os
from flask import Flask
from errors import ApiError
from response import error_response

from routes.onboarding import bp as onboarding_bp
from routes.vessels import bp as vessels_bp
from routes.listings import bp as listings_bp
from routes.offers import bp as offers_bp
from routes.escrow import bp as escrow_bp
from routes.closing import bp as closing_bp
from routes.title import bp as title_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(onboarding_bp)
    app.register_blueprint(vessels_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(escrow_bp)
    app.register_blueprint(closing_bp)
    app.register_blueprint(title_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
