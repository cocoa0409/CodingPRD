"""Quick Lube & Oil Change API — Flask entry point.

Boots EMPTY on every process start (no seeding). Under per-test-server
isolation the server is relaunched before each test; all state is rebuilt by
the test via the declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_VALIDATION
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.shops import bp as shops_bp
from routes.service_packages import bp as service_packages_bp
from routes.inspection_items import bp as inspection_items_bp
from routes.coupons import bp as coupons_bp
from routes.fleet_accounts import bp as fleet_accounts_bp
from routes.vehicles import bp as vehicles_bp
from routes.bays import bp as bays_bp
from routes.technicians import bp as technicians_bp
from routes.queue_tickets import bp as queue_tickets_bp
from routes.work_orders import bp as work_orders_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        shops_bp,
        service_packages_bp,
        inspection_items_bp,
        coupons_bp,
        fleet_accounts_bp,
        vehicles_bp,
        bays_bp,
        technicians_bp,
        queue_tickets_bp,
        work_orders_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _404(_e):
        # Unmatched route — return the envelope with a generic validation code.
        return error_response(ERR_VALIDATION, "resource not found", 404)

    @app.errorhandler(405)
    def _405(_e):
        return error_response(ERR_VALIDATION, "method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        return error_response(ERR_VALIDATION, e.description or "bad request",
                              e.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(e):
        return error_response(ERR_VALIDATION, f"internal error: {type(e).__name__}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
