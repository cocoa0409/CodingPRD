"""SNAP/EBT Flask app. Entry point."""

import os
import sys
from flask import Flask

from errors import APIError
from response import error as error_response

# Route blueprints
from routes.households import bp as households_bp
from routes.members import bp as members_bp
from routes.applications import bp as applications_bp
from routes.ebt_cards import bp as ebt_cards_bp
from routes.monthly_allotments import bp as monthly_allotments_bp
from routes.categories import bp as categories_bp
from routes.purchase_transactions import bp as purchase_transactions_bp
from routes.fraud_flags import bp as fraud_flags_bp
from routes.abawd_waivers import bp as abawd_waivers_bp
from routes.emergency_allotments import bp as emergency_allotments_bp
from routes.system_clock import bp as system_clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Don't sort JSON keys (we want stable insertion order in our views)
    app.json.sort_keys = False

    app.register_blueprint(households_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(ebt_cards_bp)
    app.register_blueprint(monthly_allotments_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(purchase_transactions_bp)
    app.register_blueprint(fraud_flags_bp)
    app.register_blueprint(abawd_waivers_bp)
    app.register_blueprint(emergency_allotments_bp)
    app.register_blueprint(system_clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        # Log but never leak details
        print(f"[unhandled] {type(e).__name__}: {e}", file=sys.stderr)
        return error_response(
            "ERR_INVALID_REQUEST", 400, f"Unexpected error: {type(e).__name__}",
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
