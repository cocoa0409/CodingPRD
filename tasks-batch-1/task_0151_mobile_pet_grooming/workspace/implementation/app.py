"""Mobile Pet Grooming API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.routes_day import bp as route_days_bp
from routes.appointments import bp as appointments_bp
from routes.plans import bp as plans_bp
from routes.fees import bp as fees_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(route_days_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(fees_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", "Internal server error: %s" % e, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
