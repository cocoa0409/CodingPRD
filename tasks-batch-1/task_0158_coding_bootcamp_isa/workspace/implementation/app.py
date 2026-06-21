"""Coding Bootcamp ISA API — Flask entry point.

In-memory store only (db.py); empty on every boot. No seeding at startup.
Boots from a fresh process under `--isolation per-test-server`.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error as error_response

from routes.cohorts import bp as cohorts_bp
from routes.applicants import bp as applicants_bp
from routes.enrollments import bp as enrollments_bp
from routes.attendance import bp as attendance_bp
from routes.scholarships import bp as scholarships_bp
from routes.deposits import bp as deposits_bp
from routes.isa_contracts import bp as isa_contracts_bp
from routes.income_reports import bp as income_reports_bp
from routes.payments import bp as payments_bp
from routes.deferments import bp as deferments_bp
from routes.refunds import bp as refunds_bp
from routes.placements import bp as placements_bp
from routes.cirr_reports import bp as cirr_reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        cohorts_bp, applicants_bp, enrollments_bp, attendance_bp,
        scholarships_bp, deposits_bp, isa_contracts_bp, income_reports_bp,
        payments_bp, deferments_bp, refunds_bp, placements_bp, cirr_reports_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        # malformed JSON etc. surface as a well-formed request error
        if err.code == 400:
            return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 400)
        return error_response(errors.ERR_INVALID_REQUEST, err.description or "Error", err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Unexpected server error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
