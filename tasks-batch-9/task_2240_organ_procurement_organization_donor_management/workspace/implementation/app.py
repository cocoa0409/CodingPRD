"""Organ Procurement Donor Management API.

A single Flask process holding every resource in memory. Nothing is read from or
written to disk, and no entity data is seeded: a freshly launched server starts
with an empty store and a logical clock reading 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes.admin import bp as admin_bp
from routes.allocation import bp as allocation_bp
from routes.authorizations import bp as authorizations_bp
from routes.donor_cases import bp as donor_cases_bp
from routes.organs import bp as organs_bp
from routes.recovery import bp as recovery_bp
from routes.referrals import bp as referrals_bp
from routes.screenings import bp as screenings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(screenings_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(donor_cases_bp)
    app.register_blueprint(organs_bp)
    app.register_blueprint(allocation_bp)
    app.register_blueprint(recovery_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST", "The method is not allowed for this path.", 405)
        return error(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be processed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
