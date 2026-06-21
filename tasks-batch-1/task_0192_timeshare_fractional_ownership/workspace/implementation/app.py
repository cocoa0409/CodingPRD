"""Timeshare & Fractional Ownership API — Flask entry point.

In-memory store only; no seeding at startup. The store is fresh on every boot.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes import (
    resorts,
    owners,
    inventory_units,
    contracts,
    points_accounts,
    reservations,
    exchange_deposits,
    invoices,
    payments,
    special_assessments,
    resale_transfers,
    delinquency_cases,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register all route modules.
    resorts.register(app)
    owners.register(app)
    inventory_units.register(app)
    contracts.register(app)
    points_accounts.register(app)
    reservations.register(app)
    exchange_deposits.register(app)
    invoices.register(app)
    payments.register(app)
    special_assessments.register(app)
    resale_transfers.register(app)
    delinquency_cases.register(app)

    # --- Error handlers (always emit the standard envelope) ---
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        body = error_response("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        body = error_response("ERR_NOT_FOUND", "Method not allowed.")
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Defensive catch-all so we never leak an HTML 500 to the test client.
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        if isinstance(exc, HTTPException):
            # Let Flask's standard handlers (404/405/etc.) produce the response.
            raise exc
        body = error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
