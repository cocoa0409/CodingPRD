"""Nurse Staffing, Acuity & Float Assignment API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.units import bp as units_bp
from routes.nurses import bp as nurses_bp
from routes.matrix_rules import bp as matrix_rules_bp
from routes.acuity_snapshots import bp as acuity_snapshots_bp
from routes.shifts import bp as shifts_bp
from routes.assignments import bp as assignments_bp
from routes.float_requests import bp as float_requests_bp
from routes.incentive_offers import bp as incentive_offers_bp
from routes.sitter_requests import bp as sitter_requests_bp
from routes.compliance_reports import bp as compliance_reports_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(units_bp)
    app.register_blueprint(nurses_bp)
    app.register_blueprint(matrix_rules_bp)
    app.register_blueprint(acuity_snapshots_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(float_requests_bp)
    app.register_blueprint(incentive_offers_bp)
    app.register_blueprint(sitter_requests_bp)
    app.register_blueprint(compliance_reports_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
