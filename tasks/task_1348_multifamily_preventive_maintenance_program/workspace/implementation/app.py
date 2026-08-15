"""Multifamily Preventive Maintenance Program API — Flask entry point.

Boots from a completely empty in-memory store on every process start.
Listens on $PORT (default 10000), bound to 0.0.0.0, in the foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.clock import bp as clock_bp
from routes.portfolio import bp as portfolio_bp
from routes.assets import bp as assets_bp
from routes.templates import bp as templates_bp
from routes.plans import bp as plans_bp
from routes.batches import bp as batches_bp
from routes.visits import bp as visits_bp
from routes.deficiencies import bp as deficiencies_bp
from routes.work_orders import bp as work_orders_bp
from routes.forecast import bp as forecast_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, portfolio_bp, assets_bp, templates_bp, plans_bp,
               batches_bp, visits_bp, deficiencies_bp, work_orders_bp,
               forecast_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
