"""Tool & Equipment Rental Yard API — Flask entry point.

Registers all route blueprints and the global error handlers. Storage is
in-memory only (see db.py); no entities are seeded at startup — the store is
empty on every boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.rate_cards import bp as rate_cards_bp
from routes.catalog_items import bp as catalog_items_bp
from routes.equipment_units import bp as equipment_units_bp
from routes.contractor_accounts import bp as contractor_accounts_bp
from routes.delivery_trucks import bp as delivery_trucks_bp
from routes.reservations import bp as reservations_bp
from routes.rental_agreements import bp as rental_agreements_bp
from routes.return_inspections import bp as return_inspections_bp
from routes.damage_charges import bp as damage_charges_bp
from routes.maintenance_tickets import bp as maintenance_tickets_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(rate_cards_bp)
    app.register_blueprint(catalog_items_bp)
    app.register_blueprint(equipment_units_bp)
    app.register_blueprint(contractor_accounts_bp)
    app.register_blueprint(delivery_trucks_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(rental_agreements_bp)
    app.register_blueprint(return_inspections_bp)
    app.register_blueprint(damage_charges_bp)
    app.register_blueprint(maintenance_tickets_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard; surface as a 400 invalid request envelope rather
        # than a raw stack trace.
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
