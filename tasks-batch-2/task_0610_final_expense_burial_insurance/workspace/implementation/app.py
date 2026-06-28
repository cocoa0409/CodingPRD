"""Final Expense & Burial Insurance API — entry point.

In-memory only. The store starts empty on every boot; nothing is seeded.
start.sh re-invocation wipes every byte of state (a fresh process).
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.product_plans import bp as product_plans_bp
from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.policies import bp as policies_bp
from routes.premium_payments import bp as premium_payments_bp
from routes.policy_loans import bp as policy_loans_bp
from routes.claims_routes import bp as claims_bp
from routes.ledger_routes import bp as ledger_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(product_plans_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(premium_payments_bp)
    app.register_blueprint(policy_loans_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(ledger_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return exc
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
