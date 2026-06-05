"""Car Rental Operations API — Flask entry point.

In-memory only; no seeding. Boots clean on every process start (per-test-server
isolation re-launches this before each test). Reads $PORT, binds 0.0.0.0, runs
in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response
from routes.incident_reports import bp as incident_reports_bp
from routes.locations import bp as locations_bp
from routes.members import bp as members_bp
from routes.rate_plans import bp as rate_plans_bp
from routes.rental_agreements import bp as rental_agreements_bp
from routes.reservations import bp as reservations_bp
from routes.testdrive import bp as testdrive_bp
from routes.vehicle_classes import bp as vehicle_classes_bp
from routes.vehicles import bp as vehicles_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Defensive wipe: the process is fresh, but this guarantees an empty store.
    db.reset()

    app.register_blueprint(locations_bp)
    app.register_blueprint(vehicle_classes_bp)
    app.register_blueprint(rate_plans_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(rental_agreements_bp)
    app.register_blueprint(incident_reports_bp)
    app.register_blueprint(testdrive_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # An unmatched route / unknown resource path.
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other HTTP exception conservatively.
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND", "method not allowed", 404)
        return error_response("ERR_INVALID_REQUEST", exc.description or "error", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
