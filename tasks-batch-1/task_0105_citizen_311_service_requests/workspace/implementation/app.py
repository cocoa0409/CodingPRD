"""Citizen 311 Service Requests API — Flask entry point.

In-memory store, starts EMPTY on every boot. Per-test-server isolation re-invokes
start.sh and a fresh process gives a clean store. No seeding at startup.
"""
import os

from flask import Flask, request

import errors
import response
from middleware import KNOWN_ROLES

from routes.config import bp as config_bp
from routes.requests import bp as requests_bp
from routes.clusters import bp as clusters_bp
from routes.work_orders import bp as work_orders_bp
from routes.escalations import bp as escalations_bp
from routes.surveys import bp as surveys_bp
from routes.windows import bp as windows_bp
from routes.clock_ctl import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(clusters_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(escalations_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(windows_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        # Unknown route. If the caller is authenticated treat as not-found,
        # otherwise still surface a not-found error in the standard envelope.
        return response.error_response(
            errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return response.error_response(
            errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected failures in the standard error envelope as a
        # schema/validation problem rather than leaking an HTML 500 page.
        return response.error_response(
            errors.ERR_INVALID_REQUEST, "Unexpected error: {}".format(err), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
