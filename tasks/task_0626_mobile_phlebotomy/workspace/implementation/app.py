"""Mobile Phlebotomy & At-Home Lab Draw API — entry point.

In-memory storage only (db.py). Nothing is seeded at startup; every entity is built
by the test via the declared API surface. Each process start wipes all state.
"""
import os

from flask import Flask

import response
from errors import ApiError
from middleware import extract_user_context

from routes.catalog import bp as catalog_bp
from routes.field import bp as field_bp
from routes.orders import bp as orders_bp
from routes.appointments import bp as appointments_bp
from routes.specimens import bp as specimens_bp
from routes.manifests import bp as manifests_bp
from routes.results import bp as results_bp
from routes.invoices import bp as invoices_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(field_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(specimens_bp)
    app.register_blueprint(manifests_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route: still validate user-context headers first (PRD 2.7 ordering),
        # then report a generic not-found. We surface header errors when applicable.
        try:
            extract_user_context()
        except ApiError as e:
            return response.error_response(e.error_id, e.message, e.http_status)
        return response.error_response("ERR_ORDER_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        try:
            extract_user_context()
        except ApiError as e:
            return response.error_response(e.error_id, e.message, e.http_status)
        return response.error_response("ERR_INSUFFICIENT_PERMISSIONS", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error_response(err.error_id, err.message, err.http_status)
        return response.error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
