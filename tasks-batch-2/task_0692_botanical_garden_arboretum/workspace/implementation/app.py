"""Entry point: error handlers + route registration.

Botanical Garden / Arboretum — Membership & Admission Platform.
Storage is in-memory only and starts EMPTY on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response
from routes.clock import bp as clock_bp
from routes.gardens import bp as gardens_bp
from routes.memberships import bp as memberships_bp
from routes.time_slots import bp as time_slots_bp
from routes.reservations import bp as reservations_bp
from routes.event_tickets import bp as event_tickets_bp
from routes.program_sessions import bp as program_sessions_bp
from routes.registrations import bp as registrations_bp
from routes.venues import bp as venues_bp
from routes.rentals import bp as rentals_bp
from routes.donations import bp as donations_bp
from routes.conservancy_funds import bp as conservancy_funds_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(gardens_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(time_slots_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(event_tickets_bp)
    app.register_blueprint(program_sessions_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(donations_bp)
    app.register_blueprint(conservancy_funds_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_VALIDATION, "Malformed request", 422)

    @app.errorhandler(415)
    def handle_415(err):
        return error_response(errors.ERR_VALIDATION, "Unsupported media type", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        if isinstance(err, HTTPException):
            code = err.code or 500
            if code == 404 or code == 405:
                return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)
            if code in (400, 415):
                return error_response(errors.ERR_VALIDATION, "Malformed request", 422)
            return error_response("ERR_INTERNAL", err.description or str(err), code)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
