"""Travel & Expense Reimbursement API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response
from routes.users import bp as users_bp
from routes.policies import bp as policies_bp
from routes.trips import bp as trips_bp
from routes.cards import bp as cards_bp
from routes.reports import bp as reports_bp
from routes.lines import bp as lines_bp
from routes.receipts import bp as receipts_bp
from routes.approval_steps import bp as approval_steps_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(users_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(lines_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(approval_steps_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path. Treat as not found in our envelope.
        body = error_response("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(exc):
        body = error_response("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            body = error_response("ERR_NOT_FOUND", exc.description or "Error")
            return jsonify(body), exc.code
        body = error_response("ERR_INVALID_REQUEST", "Unexpected server error")
        return jsonify(body), 422

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
