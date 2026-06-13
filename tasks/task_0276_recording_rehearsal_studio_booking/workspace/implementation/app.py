"""Recording / Rehearsal Studio Booking API — entry point.

In-memory only. The data store is recreated on every process boot (no seeding).
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from db import init_clock

from routes.inventory import bp as inventory_bp
from routes.bookings import bp as bookings_bp
from routes.payments import bp as payments_bp
from routes.gear_rentals import bp as gear_rentals_bp
from routes.engineer_assignments import bp as engineer_assignments_bp
from routes.lockout_contracts import bp as lockout_contracts_bp
from routes.delivery import bp as delivery_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Initialise the server-controlled wall clock at boot (PRD §2.11).
    init_clock()

    app.register_blueprint(inventory_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(gear_rentals_bp)
    app.register_blueprint(engineer_assignments_bp)
    app.register_blueprint(lockout_contracts_bp)
    app.register_blueprint(delivery_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", 400, "bad request")

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        if isinstance(exc, HTTPException):
            code = exc.code or 500
            if code == 404:
                return error_response("ERR_NOT_FOUND", 404, "resource not found")
            return error_response("ERR_INVALID_REQUEST", code if 400 <= code < 500 else 400, str(exc))
        return error_response("ERR_INVALID_REQUEST", 400, "unhandled error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
