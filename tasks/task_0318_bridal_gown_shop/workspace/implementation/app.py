"""Bridal Gown Shop API — Flask entry point. In-memory only, empty on boot."""
import os

from flask import Flask

import response
from errors import ApiError

# Route blueprints (one per resource group).
from routes.stylists import bp as stylists_bp
from routes.fitting_rooms import bp as fitting_rooms_bp
from routes.bridal_parties import bp as bridal_parties_bp
from routes.appointments import bp as appointments_bp
from routes.bookings import bp as bookings_bp
from routes.gown_orders import bp as gown_orders_bp
from routes.accessories import bp as accessories_bp
from routes.alteration_jobs import bp as alteration_jobs_bp
from routes.payment_plans import bp as payment_plans_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(stylists_bp)
    app.register_blueprint(fitting_rooms_bp)
    app.register_blueprint(bridal_parties_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(gown_orders_bp)
    app.register_blueprint(accessories_bp)
    app.register_blueprint(alteration_jobs_bp)
    app.register_blueprint(payment_plans_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace; surface a generic 500 in the envelope.
        if isinstance(err, ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        return response.error("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
