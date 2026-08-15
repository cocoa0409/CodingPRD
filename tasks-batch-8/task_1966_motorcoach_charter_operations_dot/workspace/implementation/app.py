"""Flask app entry point."""

import os
import traceback

from flask import Flask

import errors
from response import error_response

from routes.customers import bp as customers_bp
from routes.vehicles import bp as vehicles_bp
from routes.drivers import bp as drivers_bp
from routes.quotes import bp as quotes_bp
from routes.orders import bp as orders_bp
from routes.trip_logs import bp as trip_logs_bp
from routes.incidents import bp as incidents_bp
from routes.maintenance import bp as maintenance_bp
from routes.breakdowns import bp as breakdowns_bp
from routes.insurance import bp as insurance_bp
from routes.safety_audits import bp as safety_audits_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(trip_logs_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(breakdowns_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(safety_audits_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
