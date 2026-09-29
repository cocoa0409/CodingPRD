"""Household Staff Placement Agency API — entry point.

State lives only in process memory (see db.py); a fresh process therefore
starts with an entirely empty store and no entity is ever seeded at boot.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.billing import bp as billing_bp
from routes.candidates import bp as candidates_bp
from routes.cases import bp as cases_bp
from routes.clients import bp as clients_bp
from routes.clock import bp as clock_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.placements import bp as placements_bp
from routes.requisitions import bp as requisitions_bp
from routes.trials import bp as trials_bp
from routes.vetting import bp as vetting_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (
        clock_bp,
        clients_bp,
        fee_schedules_bp,
        requisitions_bp,
        candidates_bp,
        vetting_bp,
        trials_bp,
        placements_bp,
        billing_bp,
        cases_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_unknown_route(_exc):
        return error_response("ERR_INVALID_REQUEST", "Unknown route", 404)

    @app.errorhandler(405)
    def _handle_bad_method(_exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
