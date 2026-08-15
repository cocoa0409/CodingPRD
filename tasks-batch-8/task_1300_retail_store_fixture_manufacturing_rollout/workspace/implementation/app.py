"""Fixture Rollout API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError, HTTP_STATUS
from response import error_response

from routes.programs import bp as programs_bp
from routes.prototypes import bp as prototypes_bp
from routes.kits import bp as kits_bp
from routes.waves import bp as waves_bp
from routes.reservations import bp as reservations_bp
from routes.deliveries import bp as deliveries_bp
from routes.claims import bp as claims_bp
from routes.signoffs import bp as signoffs_bp
from routes.ledgers import bp as ledgers_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(prototypes_bp)
    app.register_blueprint(kits_bp)
    app.register_blueprint(waves_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(deliveries_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(signoffs_bp)
    app.register_blueprint(ledgers_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Surface unexpected errors in the standard envelope.
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
