"""Home Oxygen & Respiratory Therapy Service API.

Entry point: registers the resource blueprints under the /home-oxygen prefix
and renders every failure through the PRD 2.2 error envelope.  All state is
in-memory and starts empty on every boot -- nothing is seeded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import API_PREFIX, ApiError, respond_error
from routes.branches import bp as branches_bp
from routes.patients import bp as patients_bp
from routes.qualifying_tests import bp as tests_bp
from routes.cmns import bp as cmns_bp
from routes.contracts import bp as contracts_bp
from routes.equipment_units import bp as units_bp
from routes.placements import bp as placements_bp
from routes.delivery_routes import bp as routes_bp
from routes.route_stops import bp as stops_bp
from routes.recall_notices import bp as recalls_bp
from routes.travel_authorizations import bp as travel_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        branches_bp,
        patients_bp,
        tests_bp,
        cmns_bp,
        contracts_bp,
        units_bp,
        placements_bp,
        routes_bp,
        stops_bp,
        recalls_bp,
        travel_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return respond_error(
            "ERR_INVALID_REQUEST", exc.description or "Invalid request", exc.code
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return respond_error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
