"""Flask entry point: route registration, error handlers."""
from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.stations import bp as stations_bp
from routes.equipment import bp as equipment_bp
from routes.pricing import bp as pricing_bp
from routes.fleet import bp as fleet_bp
from routes.contracts import bp as contracts_bp
from routes.sessions import bp as sessions_bp
from routes.maintenance import bp as maintenance_bp
from routes.backups import bp as backups_bp
from routes.inspections import bp as inspections_bp
from routes.claims import bp as claims_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        stations_bp,
        equipment_bp,
        pricing_bp,
        fleet_bp,
        contracts_bp,
        sessions_bp,
        maintenance_bp,
        backups_bp,
        inspections_bp,
        claims_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _unhandled(err):
        # Never leak a stack trace as a bare 500 HTML page — return the envelope.
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
