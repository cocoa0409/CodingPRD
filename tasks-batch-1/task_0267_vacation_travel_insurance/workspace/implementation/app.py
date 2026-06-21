"""Vacation Travel Insurance API — Flask entry point.

Registers all resource blueprints and installs global error handlers that
render the standard error envelope (PRD §2.2).
"""
import os

from flask import Flask

import response
from errors import ApiError

from routes.clock import bp as clock_bp
from routes.plans import bp as plans_bp
from routes.travelers import bp as travelers_bp
from routes.named_storms import bp as named_storms_bp
from routes.policies import bp as policies_bp
from routes.claims import bp as claims_bp
from routes.payouts import bp as payouts_bp
from routes.refunds import bp as refunds_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(travelers_bp)
    app.register_blueprint(named_storms_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(refunds_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> standard NOT_FOUND envelope.
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
