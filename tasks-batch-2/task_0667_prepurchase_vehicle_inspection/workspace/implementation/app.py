"""Prepurchase Vehicle Inspection API — entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
Boots a fresh Flask process each invocation (per-test-server isolation).
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

# route blueprints
from routes.accounts import bp as accounts_bp
from routes.assignments import bp as assignments_bp
from routes.clock import bp as clock_bp
from routes.disputes import bp as disputes_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.inspectors import bp as inspectors_bp
from routes.orders import bp as orders_bp
from routes.reports import bp as reports_bp
from routes.vehicles import bp as vehicles_bp
from routes.vin_reports import bp as vin_reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(fee_schedules_bp)
    app.register_blueprint(inspectors_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(vin_reports_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        resp = jsonify(body)
        resp.status_code = exc.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(exc):
        body = error_response("ERR_NOT_FOUND", "Resource not found")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(exc):
        body = error_response("ERR_NOT_FOUND", "Method not allowed")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected errors as a generic invalid-request rather than
        # a bare 500 HTML page, but never mask ApiError (handled above).
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc)
        resp = jsonify(body)
        resp.status_code = 422
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
