"""Handyman & Appliance Repair Marketplace API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding). The
test harness reboots the server before every test via start.sh, so all state is
constructed by tests through the declared endpoints.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.pros import bp as pros_bp
from routes.jobs import bp as jobs_bp
from routes.dispatch import bp as dispatch_bp
from routes.visits import bp as visits_bp
from routes.invoices import bp as invoices_bp
from routes.disputes import bp as disputes_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pros_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(dispatch_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(disputes_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
