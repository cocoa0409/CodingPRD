"""Livestock & Herd Management API — Flask entry point.

In-memory storage only; nothing is seeded at startup. The store is a fresh,
empty Store() on every process boot (see db.py). start.sh re-launches a new
process before every test under per-test-server isolation.
"""
import os

from flask import Flask, jsonify

import errors
from response import error_response

from routes.setup import bp as setup_bp
from routes.animals import bp as animals_bp
from routes.breeding import bp as breeding_bp
from routes.health import bp as health_bp
from routes.movements import bp as movements_bp
from routes.sales import bp as sales_bp
from routes.mortality import bp as mortality_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(setup_bp)
    app.register_blueprint(animals_bp)
    app.register_blueprint(breeding_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(movements_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(mortality_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        # malformed JSON etc.
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # surface unexpected errors as a generic 422 invalid-request rather than
        # an HTML 500 page so the test harness always receives the envelope
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        import traceback
        traceback.print_exc()
        return error_response(errors.ERR_INVALID_REQUEST, "Unexpected error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
