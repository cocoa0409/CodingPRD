"""Shared Bicycle Operation System — Flask entry point.

Listens on 0.0.0.0:$PORT (default 10000).
"""
from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from middleware import authenticate
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    # Don't append "/" — clients pass exact paths.
    app.url_map.strict_slashes = False

    # Register blueprints.
    from routes import (
        audit_logs as audit_logs_routes,
        bikes as bikes_routes,
        control as control_routes,
        geofences as geofences_routes,
        loss_records as loss_records_routes,
        regions as regions_routes,
        riders as riders_routes,
        rides as rides_routes,
        transfers as transfers_routes,
        workorders as workorders_routes,
    )
    app.register_blueprint(regions_routes.bp)
    app.register_blueprint(geofences_routes.bp)
    app.register_blueprint(bikes_routes.bp)
    app.register_blueprint(riders_routes.bp)
    app.register_blueprint(rides_routes.bp)
    app.register_blueprint(workorders_routes.bp)
    app.register_blueprint(transfers_routes.bp)
    app.register_blueprint(loss_records_routes.bp)
    app.register_blueprint(audit_logs_routes.bp)
    app.register_blueprint(control_routes.bp)

    @app.before_request
    def _auth_check():
        # OPTIONS / preflight may have no auth.
        if request.method == "OPTIONS":
            return
        authenticate()

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        return error_response(
            "ERR_VALIDATION",
            exc.description or exc.name,
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_uncaught(exc: Exception):
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
