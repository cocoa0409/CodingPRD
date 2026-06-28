"""Fractional Brokerage API — Flask entry point.

In-memory storage only (db.py). NOTHING is seeded at startup: every entity is
constructed by callers through the declared endpoints. The logical clock starts
at 2026-01-01T00:00:00Z on each fresh boot (PRD §2.5)."""
import os

from flask import Flask, request

import errors
from response import error_response
from routes.accounts import bp as accounts_bp
from routes.deposits import bp as deposits_bp
from routes.securities import bp as securities_bp
from routes.orders import bp as orders_bp
from routes.settlements import bp as settlements_bp
from routes.positions import bp as positions_bp
from routes.dividends import bp as dividends_bp
from routes.options import bp as options_bp
from routes.margin import bp as margin_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(securities_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(dividends_bp)
    app.register_blueprint(options_bp)
    app.register_blueprint(margin_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
