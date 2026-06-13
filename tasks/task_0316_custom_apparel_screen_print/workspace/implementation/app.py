"""Custom Apparel & Screen-Print Shop API — Flask entry point.

In-memory state, no seeding. The store starts empty on every boot; the test
harness restarts this process before every test (per-test-server isolation).
"""
import os

from flask import Flask

from errors import ApiError
from middleware import extract_identity
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.shops import bp as shops_bp
from routes.customers import bp as customers_bp
from routes.decoration_methods import bp as decoration_methods_bp
from routes.garment_styles import bp as garment_styles_bp
from routes.machines import bp as machines_bp
from routes.orders import bp as orders_bp
from routes.art_proofs import bp as art_proofs_bp
from routes.reservations import bp as reservations_bp
from routes.production_runs import bp as production_runs_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        extract_identity()

    app.register_blueprint(clock_bp)
    app.register_blueprint(shops_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(decoration_methods_bp)
    app.register_blueprint(garment_styles_bp)
    app.register_blueprint(machines_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(art_proofs_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(production_runs_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
