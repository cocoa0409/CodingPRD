"""Photography & Videography Booking API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over
state. No entity is seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.clients import bp as clients_bp
from routes.photographers import bp as photographers_bp
from routes.session_packages import bp as session_packages_bp
from routes.bookings import bp as bookings_bp
from routes.payments import bp as payments_bp
from routes.contracts import bp as contracts_bp
from routes.shoot_schedules import bp as shoot_schedules_bp
from routes.second_shooter_assignments import bp as second_shooter_bp
from routes.galleries import bp as galleries_bp
from routes.addon_orders import bp as addon_orders_bp
from routes.license_grants import bp as license_grants_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(photographers_bp)
    app.register_blueprint(session_packages_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(shoot_schedules_bp)
    app.register_blueprint(second_shooter_bp)
    app.register_blueprint(galleries_bp)
    app.register_blueprint(addon_orders_bp)
    app.register_blueprint(license_grants_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
