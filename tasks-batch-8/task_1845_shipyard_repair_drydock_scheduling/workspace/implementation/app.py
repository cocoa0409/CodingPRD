"""Shipyard Repair & Drydock API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.docks import bp as docks_bp
from routes.vessels import bp as vessels_bp
from routes.subcontractors import bp as subcontractors_bp
from routes.projects import bp as projects_bp
from routes.reservations import bp as reservations_bp
from routes.work_items import bp as work_items_bp
from routes.change_orders import bp as change_orders_bp
from routes.surveys import bp as surveys_bp
from routes.permits import bp as permits_bp
from routes.warranty_claims import bp as warranty_claims_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(docks_bp)
    app.register_blueprint(vessels_bp)
    app.register_blueprint(subcontractors_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(work_items_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(warranty_claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Surface unexpected errors in the standard envelope.
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
