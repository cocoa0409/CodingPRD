"""Stage Lighting, Rigging & Production Services API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.venues import bp as venues_bp
from routes.technicians import bp as technicians_bp
from routes.productions import bp as productions_bp
from routes.plots import bp as plots_bp
from routes.rigging_points import bp as rigging_points_bp
from routes.assets import bp as assets_bp
from routes.pull_list_entries import bp as pull_list_entries_bp
from routes.crew_calls import bp as crew_calls_bp
from routes.crew_assignments import bp as crew_assignments_bp
from routes.power_plans import bp as power_plans_bp
from routes.trucks import bp as trucks_bp
from routes.load_schedules import bp as load_schedules_bp
from routes.inspections import bp as inspections_bp
from routes.damage_reports import bp as damage_reports_bp
from routes.settlements import bp as settlements_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        venues_bp,
        technicians_bp,
        productions_bp,
        plots_bp,
        rigging_points_bp,
        assets_bp,
        pull_list_entries_bp,
        crew_calls_bp,
        crew_assignments_bp,
        power_plans_bp,
        trucks_bp,
        load_schedules_bp,
        inspections_bp,
        damage_reports_bp,
        settlements_bp,
        clock_bp,
    ):
        app.register_blueprint(bp, url_prefix="/api")

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

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
