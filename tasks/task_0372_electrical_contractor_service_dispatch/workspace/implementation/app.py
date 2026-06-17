"""Electrical Contractor Dispatch API — Flask entry point.

Registers all route blueprints and the standard error handlers. Storage is
in-memory only (see db.py) and starts empty on every boot — no seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

# Route blueprints.
from routes.customers import bp as customers_bp
from routes.technicians import bp as technicians_bp
from routes.membership_plans import bp as membership_plans_bp
from routes.memberships import bp as memberships_bp
from routes.material_skus import bp as material_skus_bp
from routes.truck_stock import bp as truck_stock_bp
from routes.service_jobs import bp as service_jobs_bp
from routes.estimates import bp as estimates_bp
from routes.dispatches import bp as dispatches_bp
from routes.permits import bp as permits_bp
from routes.material_usages import bp as material_usages_bp
from routes.invoices import bp as invoices_bp
from routes.callbacks import bp as callbacks_bp
from routes.dispatch_queue import bp as dispatch_queue_bp
from routes.clock_admin import bp as clock_admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        customers_bp,
        technicians_bp,
        membership_plans_bp,
        memberships_bp,
        material_skus_bp,
        truck_stock_bp,
        service_jobs_bp,
        estimates_bp,
        dispatches_bp,
        permits_bp,
        material_usages_bp,
        invoices_bp,
        callbacks_bp,
        dispatch_queue_bp,
        clock_admin_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path; surface as a generic 404-style
        # not-found is misleading, so report the routing failure as 405 in the
        # standard envelope using the validation vocabulary.
        return response.error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Any other werkzeug HTTPException -> standard envelope.
        return response.error_response("ERR_INVALID_REQUEST", e.description or "Request error", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last-resort guard so the server never leaks an HTML 500 page.
        return response.error_response("ERR_INVALID_REQUEST", "Unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
