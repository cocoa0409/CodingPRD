"""Haunted House & Seasonal Attraction API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot. No seeding.
Reads PORT from the environment, binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

from routes.clock import bp as clock_bp
from routes.venues import bp as venues_bp
from routes.attractions import bp as attractions_bp
from routes.pricing_rules import bp as pricing_rules_bp
from routes.time_slots import bp as time_slots_bp
from routes.guests import bp as guests_bp
from routes.waivers import bp as waivers_bp
from routes.passes import bp as passes_bp
from routes.reservations import bp as reservations_bp
from routes.scare_zones import bp as scare_zones_bp
from routes.closures import bp as closures_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(attractions_bp)
    app.register_blueprint(pricing_rules_bp)
    app.register_blueprint(time_slots_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(waivers_bp)
    app.register_blueprint(passes_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(scare_zones_bp)
    app.register_blueprint(closures_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # No matching method on a known path -> treat as not found in our envelope.
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Bad request.", 400)
        return response.error("ERR_INVALID_REQUEST", str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INVALID_REQUEST", "Unexpected error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
