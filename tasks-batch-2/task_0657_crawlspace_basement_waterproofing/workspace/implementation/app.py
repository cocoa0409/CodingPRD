"""Crawlspace Waterproofing API — Flask entry point.

In-memory only. The store starts empty on every boot; no entities are seeded.
"""
import os

from flask import Flask, request

import errors
from response import error_response

from routes.admin import bp as admin_bp
from routes.homeowners import bp as homeowners_bp
from routes.crews import bp as crews_bp
from routes.jobs import bp as jobs_bp
from routes.inspections import bp as inspections_bp
from routes.quotes import bp as quotes_bp
from routes.financing import bp as financing_bp
from routes.install_orders import bp as install_orders_bp
from routes.crew_bookings import bp as crew_bookings_bp
from routes.warranties import bp as warranties_bp
from routes.service_visits import bp as service_visits_bp
from routes.claims import bp as claims_bp
from routes.foundation_referrals import bp as foundation_referrals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        admin_bp, homeowners_bp, crews_bp, jobs_bp, inspections_bp, quotes_bp,
        financing_bp, install_orders_bp, crew_bookings_bp, warranties_bp,
        service_visits_bp, claims_bp, foundation_referrals_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, 404, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Unexpected error: %s" % exc)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
