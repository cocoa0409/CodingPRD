"""Public Library Management API — Flask entry point.

In-memory storage only (see db.py). The store starts empty on every boot; no
entity is ever seeded, preloaded, or hardcoded. The harness re-launches this
process via start.sh before every test, so a fresh process == a clean slate.
"""

import os

from flask import Flask, jsonify

import errors
import response

from routes.branches import bp as branches_bp
from routes.patrons import bp as patrons_bp
from routes.titles import bp as titles_bp
from routes.copies import bp as copies_bp
from routes.loans import bp as loans_bp
from routes.holds import bp as holds_bp
from routes.resources import bp as resources_bp
from routes.reservations import bp as reservations_bp
from routes.ill_requests import bp as ill_requests_bp
from routes.license_pools import bp as license_pools_bp
from routes.fines import bp as fines_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        branches_bp, patrons_bp, titles_bp, copies_bp, loans_bp, holds_bp,
        resources_bp, reservations_bp, ill_requests_bp, license_pools_bp,
        fines_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    # Root route: lets the harness health-poll GET / get any HTTP response.
    @app.get("/")
    def root():
        return jsonify({"service": "public-library-management", "status": "ok"})

    # --- Error handlers ----------------------------------------------------

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route / method on a known path -> ERR_NOT_FOUND envelope.
        return response.error_response(
            errors.ERR_NOT_FOUND, "Resource not found.", 404
        )

    @app.errorhandler(405)
    def handle_405(_exc):
        return response.error_response(
            errors.ERR_NOT_FOUND, "Method not allowed.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak a raw 500 in the wrong shape; wrap as an envelope.
        if isinstance(exc, errors.ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        return response.error_response(
            "ERR_INTERNAL", f"Internal server error: {exc}", 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
