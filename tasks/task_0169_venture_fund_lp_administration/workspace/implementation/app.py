"""Venture Fund / LP Administration API — Flask entry point.

In-memory storage only; state starts EMPTY on every boot (no seeding). The
per-test-server isolation re-launches this process before every test.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.funds import bp as funds_bp
from routes.limited_partners import bp as lps_bp
from routes.commitments import bp as commitments_bp
from routes.capital_calls import bp as capital_calls_bp
from routes.allocations import bp as allocations_bp
from routes.portfolio import bp as portfolio_bp
from routes.valuation_marks import bp as valuation_marks_bp
from routes.fee_accruals import bp as fee_accruals_bp
from routes.distributions import bp as distributions_bp
from routes.side_letters import bp as side_letters_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(funds_bp)
    app.register_blueprint(lps_bp)
    app.register_blueprint(commitments_bp)
    app.register_blueprint(capital_calls_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(valuation_marks_bp)
    app.register_blueprint(fee_accruals_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(side_letters_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / path -> resource not found.
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404
        )

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", "Method not allowed.", 404
        )

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        if isinstance(err, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(err), err.code or 400)
        # Last-resort: surface as a 400 invalid request rather than a 500 page.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
