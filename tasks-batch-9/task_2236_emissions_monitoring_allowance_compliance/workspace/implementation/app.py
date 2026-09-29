"""Flask entry point.

Boots a completely empty in-memory store on every process start: no seeding,
no preloading, no persistence of any kind. Every blueprint registers its own
routes under the ``/emissions`` prefix.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    allowances,
    clock,
    control_outages,
    excess_events,
    facilities,
    fuel_samples,
    monitoring_systems,
    operating_hours,
    permit_limits,
    quarterly_reports,
    rata_tests,
    units,
)

BLUEPRINTS = (
    clock.bp,
    facilities.bp,
    units.bp,
    monitoring_systems.bp,
    rata_tests.bp,
    fuel_samples.bp,
    operating_hours.bp,
    quarterly_reports.bp,
    permit_limits.bp,
    excess_events.bp,
    allowances.bp,
    control_outages.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_INVALID_REQUEST", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
