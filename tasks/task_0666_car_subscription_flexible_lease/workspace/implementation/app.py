"""Car Subscription & Flexible Lease API — Flask entry point.

In-memory storage only; state is wiped on every process restart. No entity seeding
at startup — tests build all data via the API.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response
import errors as err

from routes.catalog import bp as catalog_bp
from routes.applicants import bp as applicants_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.billing import bp as billing_bp
from routes.swaps import bp as swaps_bp
from routes.returns import bp as returns_bp
from routes.logistics import bp as logistics_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(swaps_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope (consistent error shape).
        return error_response(err.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Fall back to a generic invalid-request envelope rather than an HTML 500.
        return error_response(err.ERR_INVALID_REQUEST, str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
