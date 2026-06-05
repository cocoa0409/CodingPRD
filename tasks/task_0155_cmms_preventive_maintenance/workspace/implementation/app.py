"""CMMS Preventive Maintenance API — Flask entry point.

In-memory only: all state lives in db.py module dicts and is wiped on every
process boot. Nothing is seeded at startup.
"""
import os

from flask import Flask

import errors
from response import error_response

from routes.sites import bp as sites_bp
from routes.spare_parts import bp as spare_parts_bp
from routes.technicians import bp as technicians_bp
from routes.assets import bp as assets_bp
from routes.meter_readings import bp as meter_readings_bp
from routes.pm_schedules import bp as pm_schedules_bp
from routes.work_orders import bp as work_orders_bp
from routes.reservations import bp as reservations_bp
from routes.downtime_events import bp as downtime_events_bp
from routes.warranty_claims import bp as warranty_claims_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(sites_bp)
    app.register_blueprint(spare_parts_bp)
    app.register_blueprint(technicians_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(meter_readings_bp)
    app.register_blueprint(pm_schedules_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(downtime_events_bp)
    app.register_blueprint(warranty_claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # Unknown method on a known path -> treat as not found per envelope.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response(errors.ERR_INVALID_REQUEST, "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
