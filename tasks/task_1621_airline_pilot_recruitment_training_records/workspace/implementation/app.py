"""Airline Pilot Training Records API — Flask entry point.

In-memory only: every process boot starts with an empty store and the logical
clock at 2026-08-01T00:00:00Z. Nothing is seeded or persisted.
"""

import os

from flask import Flask

from errors import ApiError
from util import error_response
from routes.applicants import bp as applicants_bp
from routes.classes import bp as classes_bp
from routes.events import bp as events_bp
from routes.quals import bp as quals_bp
from routes.bids import bp as bids_bp
from routes.resources import bp as resources_bp
from routes.ops import bp as ops_bp

API_PREFIX = "/pilot-training"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (applicants_bp, classes_bp, events_bp, quals_bp, bids_bp,
                      resources_bp, ops_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unexpected error")
        return error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected error: %s" % err), )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
