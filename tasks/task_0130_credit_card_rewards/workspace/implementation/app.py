"""Flask application entry point for the Credit Card Rewards API."""
from __future__ import annotations

import os
import traceback

from flask import Flask, request

from auth import auth_middleware
from errors import APIError
from response import error_response

from routes.cardholders import bp as cardholders_bp
from routes.accounts import bp as accounts_bp
from routes.categories import bp as categories_bp
from routes.transactions import bp as transactions_bp
from routes.transfer_partners import bp as transfer_partners_bp
from routes.points_transfers import bp as points_transfers_bp
from routes.statement_credits import bp as statement_credits_bp
from routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False  # preserve insertion order for stable envelope shapes
    app.url_map.strict_slashes = False

    # ---- global before-request: auth (priority 1, 2 of the validation table) ----
    @app.before_request
    def _global_auth():
        try:
            auth_middleware()
        except APIError as e:
            return error_response(e.error_id, e.message, e.http_status)

    # ---- error handlers ----
    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        # The PRD does not enumerate 405; map to 404 to keep the error surface
        # within the documented catalog.
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(Exception)
    def _handle_unhandled(e):
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Internal error: {e}", 422)

    # ---- register blueprints ----
    app.register_blueprint(system_bp)  # registered first so its routes resolve quickly
    app.register_blueprint(cardholders_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(transfer_partners_bp)
    app.register_blueprint(points_transfers_bp)
    app.register_blueprint(statement_credits_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
