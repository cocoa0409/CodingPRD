"""Sewer CCTV Inspection & Rehabilitation API — Flask application entry point."""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes import (
    districts, technicians, cycles, segments, inspections, plans,
    work_orders, bypass, notices, warranty, flow, clock,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    app.register_blueprint(clock.bp)
    app.register_blueprint(districts.bp)
    app.register_blueprint(technicians.bp)
    app.register_blueprint(cycles.bp)
    app.register_blueprint(segments.bp)
    app.register_blueprint(inspections.bp)
    app.register_blueprint(plans.bp)
    app.register_blueprint(work_orders.bp)
    app.register_blueprint(bypass.bp)
    app.register_blueprint(notices.bp)
    app.register_blueprint(warranty.bp)
    app.register_blueprint(flow.bp)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "route or resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", 400, "malformed request")

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", 500, f"internal error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
