"""Brow & Lash Studio API — entry point, error handlers, route registration.

In-memory state only. No seeding: the store starts empty on every boot and all
entities are created via the API by the tests.
"""
import os

from flask import Flask, jsonify

import errors
from response import error as error_response
from routes.appointments import bp as appointments_bp
from routes.clock_route import bp as clock_bp
from routes.config import bp as config_bp
from routes.members import bp as members_bp
from routes.memberships import bp as memberships_bp
from routes.retail import bp as retail_bp
from routes.schedules import bp as schedules_bp
from routes.techs import bp as techs_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(techs_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(retail_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route -> generic 404 in the standard envelope.
        return error_response(errors.ERR_STUDIO_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Bad request.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        # Last-resort: surface as a 400 invalid request rather than a bare 500
        # HTML page, keeping the JSON envelope contract.
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Unexpected error: %s" % exc)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
