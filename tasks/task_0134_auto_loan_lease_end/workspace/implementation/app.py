"""Flask application entry point — Auto Loan & Lease End API."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.customers import bp as customers_bp
from routes.delinquency_events import bp as delinquency_events_bp
from routes.gap_riders import bp as gap_riders_bp
from routes.lease_contracts import bp as lease_contracts_bp
from routes.loan_contracts import bp as loan_contracts_bp
from routes.payments import bp as payments_bp
from routes.vehicles import bp as vehicles_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(loan_contracts_bp)
    app.register_blueprint(lease_contracts_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(gap_riders_bp)
    app.register_blueprint(delinquency_events_bp)

    @app.post("/__test__/reset")
    def __test_reset():
        """Wipe all in-memory state between tests (test-only helper)."""
        from db import store
        store.reset()
        return jsonify({"ok": True}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_INVALID_REQUEST", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST", "Method Not Allowed", 400)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response("ERR_INVALID_REQUEST", exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
