"""Flask app entrypoint."""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify

# Make sibling modules importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

import routes_areas
import routes_clock
import routes_containers
import routes_manifests
import routes_partners
import routes_reports
import routes_sites
import routes_streams


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_sites.bp)
    app.register_blueprint(routes_streams.bp)
    app.register_blueprint(routes_areas.bp)
    app.register_blueprint(routes_containers.bp)
    app.register_blueprint(routes_partners.bp)
    app.register_blueprint(routes_manifests.bp)
    app.register_blueprint(routes_reports.bp)
    app.register_blueprint(routes_clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "method not allowed"))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, 400, "malformed request"))

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, ApiError):
            return error_response(err)
        # Unexpected
        return error_response(ApiError(ERR_INVALID_REQUEST, 400, str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
