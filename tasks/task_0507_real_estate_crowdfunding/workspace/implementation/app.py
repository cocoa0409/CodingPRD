"""Real Estate Crowdfunding API — entry point.

In-memory only. Store boots EMPTY on every process start (no seeding).
Reads $PORT, binds 0.0.0.0, runs in foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response

from routes.funds import bp as funds_bp
from routes.investors import bp as investors_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.holdings import bp as holdings_bp
from routes.distributions import bp as distributions_bp
from routes.redemptions import bp as redemptions_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(funds_bp)
    app.register_blueprint(investors_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(holdings_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(redemptions_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
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
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Defensive: never leak a 500 without the envelope.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error", 400)

    return app


# Store starts empty — no seeding anywhere.
db.reset()
app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
