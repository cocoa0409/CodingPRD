"""EV Battery Swap API — Flask entry point."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound, MethodNotAllowed

from errors import APIError
from response import error_response

from routes.stations import bp as stations_bp
from routes.battery_models import bp as battery_models_bp
from routes.vehicle_models import bp as vehicle_models_bp
from routes.compatibility_rules import bp as compatibility_rules_bp
from routes.batteries import bp as batteries_bp
from routes.vehicles import bp as vehicles_bp
from routes.members import bp as members_bp
from routes.reservations import bp as reservations_bp
from routes.swap_events import bp as swap_events_bp
from routes.dispatch_orders import bp as dispatch_orders_bp
from routes.recalls import bp as recalls_bp
from routes.billing_records import bp as billing_records_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.test_only import bp as test_only_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    app.register_blueprint(stations_bp)
    app.register_blueprint(battery_models_bp)
    app.register_blueprint(vehicle_models_bp)
    app.register_blueprint(compatibility_rules_bp)
    app.register_blueprint(batteries_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(swap_events_bp)
    app.register_blueprint(dispatch_orders_bp)
    app.register_blueprint(recalls_bp)
    app.register_blueprint(billing_records_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(test_only_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(NotFound)
    def _handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(MethodNotAllowed)
    def _handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        status = err.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", 404, err.description or "Not found")
        if status == 400:
            return error_response("ERR_INVALID_INPUT", 422, err.description or "Bad request")
        return error_response("ERR_INVALID_INPUT", status if 400 <= status < 600 else 422,
                              err.description or "HTTP error")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response("ERR_INVALID_INPUT", 500, f"Internal error: {err}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
