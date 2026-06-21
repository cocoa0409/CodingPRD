"""Donor-Advised Fund Administration API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding). Run in
the foreground binding 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response

# Route blueprints.
from routes.sponsors import bp as sponsors_bp
from routes.pools import bp as pools_bp
from routes.charities import bp as charities_bp
from routes.accounts import bp as accounts_bp
from routes.contributions import bp as contributions_bp
from routes.receipts import bp as receipts_bp
from routes.allocations import bp as allocations_bp
from routes.rebalance import bp as rebalance_bp
from routes.grants import bp as grants_bp
from routes.succession import bp as succession_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(sponsors_bp)
    app.register_blueprint(pools_bp)
    app.register_blueprint(charities_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(rebalance_bp)
    app.register_blueprint(grants_bp)
    app.register_blueprint(succession_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        # Unknown route / path-referenced resource not found -> ERR_NOT_FOUND.
        return error_response(
            "ERR_NOT_FOUND", "Referenced resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            "ERR_NOT_FOUND", "Referenced resource does not exist.", 404)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response(
            "ERR_INVALID_REQUEST",
            "Malformed body, invalid enum, missing required field, or amount <= 0.",
            400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected server errors as a generic invalid-request rather than
        # an HTML 500 page, keeping the JSON envelope contract intact.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response(
            "ERR_INVALID_REQUEST",
            "Malformed body, invalid enum, missing required field, or amount <= 0.",
            400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
