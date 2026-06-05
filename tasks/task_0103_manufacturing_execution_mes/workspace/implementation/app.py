"""Manufacturing Execution System (MES) API — Flask entry point.

In-memory only: all state lives in db.py module dicts and is wiped on every
process boot. Nothing is seeded at startup.
"""
import os

from flask import Flask

import errors
from response import error_response

from routes.products import bp as products_bp
from routes.routings import bp as routings_bp
from routes.machines import bp as machines_bp
from routes.lots import bp as lots_bp
from routes.work_orders import bp as work_orders_bp
from routes.work_order_operations import bp as wops_bp
from routes.scrap_dispositions import bp as scrap_bp
from routes.lot_issues import bp as lot_issues_bp
from routes.component_demands import bp as component_demands_bp
from routes.genealogy_links import bp as genealogy_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(products_bp)
    app.register_blueprint(routings_bp)
    app.register_blueprint(machines_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(wops_bp)
    app.register_blueprint(scrap_bp)
    app.register_blueprint(lot_issues_bp)
    app.register_blueprint(component_demands_bp)
    app.register_blueprint(genealogy_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface anything unexpected as an invalid request rather than a bare
        # HTML 500 so the envelope contract holds.
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response(errors.ERR_INVALID_REQUEST, "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
