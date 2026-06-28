"""Workplace Giving & Matching-Gifts Platform — Flask entry point.

In-memory only; no seeding at startup. Storage is recreated fresh on each
process start (db.py module-level Store()). start.sh re-launches this before
every per-test run.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.programs import bp as programs_bp
from routes.employees import bp as employees_bp
from routes.charities import bp as charities_bp
from routes.campaigns import bp as campaigns_bp
from routes.donations import bp as donations_bp
from routes.payroll import bp as payroll_bp
from routes.matching_gifts import bp as matching_gifts_bp
from routes.volunteer_logs import bp as volunteer_logs_bp
from routes.disbursement import bp as disbursement_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(charities_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(donations_bp)
    app.register_blueprint(payroll_bp)
    app.register_blueprint(matching_gifts_bp)
    app.register_blueprint(volunteer_logs_bp)
    app.register_blueprint(disbursement_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Referenced resource id does not exist", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Map remaining HTTP errors (e.g. malformed JSON -> 400) to the envelope.
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)
        return error_response("ERR_INVALID_REQUEST", str(e), e.code or 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
