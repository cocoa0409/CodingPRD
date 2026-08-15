"""Lift Station Ops API — Flask entry point.

All routes are mounted under the /lift-station-ops prefix (SCAFFOLD api_prefix).
The store starts empty on every boot; the logical clock defaults to
2026-08-01T00:00:00Z (PRD 2.9).
"""
import os

from flask import Flask

from envelope import error as error_response
from errors import ApiError

import routes_stations
import routes_pumps
import routes_operators
import routes_alarms
import routes_rebuilds
import routes_cleanings
import routes_gentests
import routes_sso
import routes_permits
import routes_capital
import routes_spares
import routes_clock

API_PREFIX = "/lift-station-ops"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        routes_stations,
        routes_pumps,
        routes_operators,
        routes_alarms,
        routes_rebuilds,
        routes_cleanings,
        routes_gentests,
        routes_sso,
        routes_permits,
        routes_capital,
        routes_spares,
        routes_clock,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION_AGGREGATE", 500, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
