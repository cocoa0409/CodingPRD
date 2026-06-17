"""Tire Shop & Service API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test via start.sh, so there is no carry-over state. No entity
seeding happens at startup — every row tests need is created through the
declared API surface.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.customers import bp as customers_bp
from routes.vehicles import bp as vehicles_bp
from routes.tire_models import bp as tire_models_bp
from routes.fitment_rules import bp as fitment_rules_bp
from routes.service_bays import bp as service_bays_bp
from routes.work_orders import bp as work_orders_bp
from routes.road_hazard import bp as road_hazard_bp
from routes.appointments import bp as appointments_bp
from routes.special_orders import bp as special_orders_bp
from routes.mileage_claims import bp as mileage_claims_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(tire_models_bp)
    app.register_blueprint(fitment_rules_bp)
    app.register_blueprint(service_bays_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(road_hazard_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(special_orders_bp)
    app.register_blueprint(mileage_claims_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(
            ERR_INVALID_REQUEST,
            str(getattr(e, "description", e)) or "bad request",
            422,
        )

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(
                ERR_INVALID_REQUEST,
                e.description or str(e),
                e.code or 500,
            )
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
