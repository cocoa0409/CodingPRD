"""Traveling Carnival Route & Contract Management API.

Flask application factory and process entry point.  All state lives in
process-local Python dicts (see db.py); the store boots empty every time.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error_body
from routes.allocations import bp as allocations_bp
from routes.contracts import bp as contracts_bp
from routes.crew import bp as crew_bp
from routes.inspections import bp as inspections_bp
from routes.money import bp as money_bp
from routes.permits import bp as permits_bp
from routes.reference import bp as reference_bp
from routes.routes_api import bp as routes_bp
from routes.stops import bp as stops_bp
from routes.weather import bp as weather_bp

BLUEPRINTS = (
    reference_bp,
    routes_bp,
    stops_bp,
    contracts_bp,
    allocations_bp,
    permits_bp,
    inspections_bp,
    crew_bp,
    money_bp,
    weather_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return jsonify(error_body(
                errors.ERR_ROUTE_NOT_FOUND, "The requested resource does not "
                "exist.")), 404
        if exc.code == 405:
            return jsonify(error_body(
                errors.ERR_INVALID_REQUEST,
                "The HTTP method is not allowed for this resource.")), 405
        if exc.code in (400, 415):
            return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                      "Request body is invalid.")), 400
        return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                  exc.description or "Request failed.")), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        return jsonify(error_body("ERR_INTERNAL", str(exc) or
                                  "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=False, use_reloader=False)
