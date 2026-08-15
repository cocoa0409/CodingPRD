"""Flask application entry point for the Pump & Valve Repair / Rebuild Center API."""
from __future__ import annotations

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        assets,
        capacity_windows,
        certifications,
        clock,
        customers,
        inspection_reports,
        parts,
        pool_units,
        quotes,
        repair_orders,
        test_runs,
    )

    app.register_blueprint(clock.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(assets.bp)
    app.register_blueprint(repair_orders.bp)
    app.register_blueprint(inspection_reports.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(parts.bp)
    app.register_blueprint(pool_units.bp)
    app.register_blueprint(test_runs.bp)
    app.register_blueprint(certifications.bp)
    app.register_blueprint(capacity_windows.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_response("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", f"Internal error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
