"""Optometry & Vision Plan API — Flask entry point.

In-memory storage only (Python dicts in db.py). The store is constructed fresh
on every process boot and NO entity data is seeded, preloaded, or hardcoded at
startup. Every entity is created by tests via the declared endpoints.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.clock_routes import bp as clock_bp
from routes.providers import bp as providers_bp
from routes.patients import bp as patients_bp
from routes.encounters import bp as encounters_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.eligibilities import bp as eligibilities_bp
from routes.lab_orders import bp as lab_orders_bp
from routes.claims import bp as claims_bp
from routes.recall_reminders import bp as recall_reminders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(encounters_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(eligibilities_bp)
    app.register_blueprint(lab_orders_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(recall_reminders_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unmatched route -> ERR_NOT_FOUND envelope
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response(
            "ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Map any other werkzeug HTTP error into the standard envelope.
        status = err.code or 500
        if status == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Bad request", 422)
        return response.error_response(
            "ERR_INVALID_REQUEST", err.description or "Request error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
