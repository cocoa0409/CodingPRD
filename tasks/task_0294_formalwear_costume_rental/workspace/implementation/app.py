"""Formalwear & Costume Rental API — entry point.

In-memory only; the store starts empty on every process boot (per-test-server
isolation). No seeding, preloading, or hardcoded entity data.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.catalogs import bp as catalogs_bp
from routes.garment_units import bp as garment_units_bp
from routes.customers import bp as customers_bp
from routes.reservations import bp as reservations_bp
from routes.alterations import bp as alterations_bp
from routes.fit_checks import bp as fit_checks_bp
from routes.party_orders import bp as party_orders_bp
from routes.settlements import bp as settlements_bp
from routes.ledger_entries import bp as ledger_entries_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalogs_bp)
    app.register_blueprint(garment_units_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(alterations_bp)
    app.register_blueprint(fit_checks_bp)
    app.register_blueprint(party_orders_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(ledger_entries_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface anything unexpected as a generic invalid-request rather than HTML.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
