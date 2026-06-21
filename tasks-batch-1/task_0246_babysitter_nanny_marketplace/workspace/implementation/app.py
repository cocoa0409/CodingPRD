"""Babysitter & Nanny Marketplace API — Flask entry point.

In-memory storage only (db.store). No seeding at startup: the store boots
empty and every entity is created via the API by the test suite.
"""

import os

from flask import Flask

import errors
from response import error as error_response
from routes.clock import bp as clock_bp
from routes.families import bp as families_bp
from routes.caregivers import bp as caregivers_bp
from routes.background_checks import bp as background_checks_bp
from routes.job_postings import bp as job_postings_bp
from routes.interviews import bp as interviews_bp
from routes.bookings import bp as bookings_bp
from routes.sessions import bp as sessions_bp
from routes.backup_requests import bp as backup_requests_bp
from routes.payouts import bp as payouts_bp
from routes.reviews import bp as reviews_bp
from routes.tax_statements import bp as tax_statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(families_bp)
    app.register_blueprint(caregivers_bp)
    app.register_blueprint(background_checks_bp)
    app.register_blueprint(job_postings_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(backup_requests_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(tax_statements_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", f"Unexpected error: {exc}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
