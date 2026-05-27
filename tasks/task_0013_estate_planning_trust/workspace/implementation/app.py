"""Flask application entry point.

Boots a fresh, empty in-memory store on every process start.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, request

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED
from response import error as error_response

from routes.assets import bp as assets_bp
from routes.clock import bp as clock_bp
from routes.creditor_claims import bp as claims_bp
from routes.decedents import bp as decedents_bp
from routes.designations import bp as designations_bp
from routes.directives import bp as directives_bp
from routes.estates import bp as estates_bp
from routes.executors import bp as executors_bp
from routes.guardianships import bp as guardianships_bp
from routes.poas import bp as poas_bp
from routes.probate_orders import bp as orders_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints
    app.register_blueprint(decedents_bp)
    app.register_blueprint(estates_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(designations_bp)
    app.register_blueprint(executors_bp)
    app.register_blueprint(poas_bp)
    app.register_blueprint(directives_bp)
    app.register_blueprint(guardianships_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response(ERR_NOT_FOUND, "Route not found.", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response(ERR_UNAUTHORIZED, "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response(ERR_INVALID_REQUEST, "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_other(e):
        # Surface unexpected exceptions as ERR_INVALID_REQUEST 400 by default
        # rather than Flask's default HTML 500 -- testers expect JSON envelope.
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        msg = f"Internal error: {type(e).__name__}: {e}"
        return error_response(ERR_INVALID_REQUEST, msg, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
