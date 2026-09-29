"""Microtransit on-demand transit service -- Flask application factory.

Storage is entirely in process memory: nothing is persisted, nothing is seeded
and nothing is preloaded.  Every boot starts from an empty store with the
logical clock reading exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (assignments, blocks, fleet, forecasts, reports, stops,
                    trips, zones)

BLUEPRINTS = (
    zones.bp,
    stops.bp,
    fleet.bp,
    forecasts.bp,
    blocks.bp,
    trips.bp,
    assignments.bp,
    reports.bp,
)

_HTTP_ERROR_IDS = {
    404: ("ERR_NOT_FOUND", "The requested resource does not exist."),
    405: ("ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed here."),
    400: ("ERR_INVALID_REQUEST", "The request could not be understood."),
    415: ("ERR_INVALID_REQUEST", "The request body must be JSON."),
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message,
                                       error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        error_id, message = _HTTP_ERROR_IDS.get(
            error.code, ("ERR_INVALID_REQUEST", error.description or "Request failed."))
        return response.error_response(error_id, message, error.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - defensive
        return response.error_response("ERR_INTERNAL", str(error) or
                                       "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
