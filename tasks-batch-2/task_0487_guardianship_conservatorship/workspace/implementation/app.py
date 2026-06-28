"""Guardianship & Conservatorship Case Management API — entry point.

Boots a fresh, empty in-memory store on every invocation. Storage is Python dicts
keyed by id (see db.py); nothing is seeded at startup. The test harness restarts
this process via start.sh before every test.
"""

import os

from flask import Flask, request

from errors import ApiError
from response import error_response, object_response
from middleware import get_identity

from routes.reference import bp as reference_bp
from routes.cases import bp as cases_bp
from routes.petitions import bp as petitions_bp
from routes.appointments import bp as appointments_bp
from routes.estate import bp as estate_bp
from routes.expenditures import bp as expenditures_bp
from routes.accountings import bp as accountings_bp
from routes.careplans import bp as careplans_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(petitions_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(estate_bp)
    app.register_blueprint(expenditures_bp)
    app.register_blueprint(accountings_bp)
    app.register_blueprint(careplans_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route. Still require auth semantics where possible, but a route
        # that does not exist is simply not found.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {exc}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
