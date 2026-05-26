"""Dog Walking & Pet Boarding API — Flask entry point.

Fresh boot: empty stores, no seeding, no on-disk persistence.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound

import response
from errors import ApiError


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register routes.
    from routes.clock import bp as clock_bp
    from routes.owners import bp as owners_bp
    from routes.sitters import bp as sitters_bp
    from routes.background_checks import bp as bg_checks_bp
    from routes.pets import bp as pets_bp
    from routes.emergency_contacts import bp as ec_bp
    from routes.meet_and_greets import bp as mg_bp
    from routes.bookings import bp as bookings_bp
    from routes.key_handoffs import bp as kh_bp
    from routes.gps_tracks import bp as gps_bp
    from routes.insurance_claims import bp as claims_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(sitters_bp)
    app.register_blueprint(bg_checks_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(ec_bp)
    app.register_blueprint(mg_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(kh_bp)
    app.register_blueprint(gps_bp)
    app.register_blueprint(claims_bp)

    # ------------- Error handlers -------------
    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(NotFound)
    def _handle_not_found(err):
        return response.error("ERR_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(MethodNotAllowed)
    def _handle_method_not_allowed(err):
        return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException):
        return response.error("ERR_HTTP", err.description or err.name, err.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        import traceback

        traceback.print_exc(file=sys.stderr)
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
