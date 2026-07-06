"""Wine, Brewery & Food Tour Operator API — entry point.

Registers all route blueprints and the global error handlers. Storage is
in-memory only (see db.py); the store starts EMPTY on every boot and no entity
is seeded. The logical clock resets to 2026-03-01T00:00:00Z each boot.
"""
import os
from flask import Flask

import errors
from response import error_response

from routes.admin import bp as admin_bp
from routes.tour_products import bp as tour_products_bp
from routes.add_ons import bp as add_ons_bp
from routes.vehicles import bp as vehicles_bp
from routes.partner_venues import bp as partner_venues_bp
from routes.pickup_points import bp as pickup_points_bp
from routes.guests import bp as guests_bp
from routes.departures import bp as departures_bp
from routes.stops import bp as stops_bp
from routes.venue_confirmations import bp as venue_confirmations_bp
from routes.bookings import bp as bookings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(tour_products_bp)
    app.register_blueprint(add_ons_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(partner_venues_bp)
    app.register_blueprint(pickup_points_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(departures_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(venue_confirmations_bp)
    app.register_blueprint(bookings_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route path -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
