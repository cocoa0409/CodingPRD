"""Cruise Port Terminal Operations API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_body

from routes.clock import bp as clock_bp
from routes.terminals import bp as terminals_bp
from routes.berths import bp as berths_bp
from routes.vessels import bp as vessels_bp
from routes.port_calls import bp as port_calls_bp
from routes.berth_assignments import bp as berth_assignments_bp
from routes.manifest import bp as manifest_bp
from routes.baggage import bp as baggage_bp
from routes.lanes import bp as lanes_bp
from routes.customs import bp as customs_bp
from routes.service_orders import bp as service_orders_bp
from routes.invoices import bp as invoices_bp
from routes.transport import bp as transport_bp
from routes.advisories import bp as advisories_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    for bp in (
        clock_bp,
        terminals_bp,
        berths_bp,
        vessels_bp,
        port_calls_bp,
        berth_assignments_bp,
        manifest_bp,
        baggage_bp,
        lanes_bp,
        customs_bp,
        service_orders_bp,
        invoices_bp,
        transport_bp,
        advisories_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_VALIDATION, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
