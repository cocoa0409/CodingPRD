"""Demand-Response VPP API — Flask entry point.

Boots with an empty in-memory store on every process start. No entity seeding.
"""
import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, err
from common import error_response

from routes_parties import bp_parties
from routes_devices import bp_devices
from routes_enrollments import bp_enrollments
from routes_events import bp_events
from routes_settlements import bp_settlements


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(bp_parties)
    app.register_blueprint(bp_devices)
    app.register_blueprint(bp_enrollments)
    app.register_blueprint(bp_events)
    app.register_blueprint(bp_settlements)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _handle_404(e):
        # Unknown route -> generic validation-style 404 envelope is not defined;
        # surface as a not-found-shaped error so the envelope stays consistent.
        return error_response(ApiError("ERR_VALIDATION", 404, "No such route."))

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response(ApiError("ERR_VALIDATION", 405, "Method not allowed."))

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        if isinstance(e, HTTPException):
            return error_response(ApiError("ERR_VALIDATION", e.code or 500, str(e)))
        return error_response(ApiError("ERR_VALIDATION", 500, "Internal error: %s" % e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
