"""Load Planning & Weight and Balance Control — Flask application factory.

Storage is entirely in-memory and nothing is seeded: every boot starts empty and
all preconditions are built through the API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    audits,
    cargo,
    clock_routes,
    distribution,
    environment,
    fleet,
    flights,
    load_plans,
    sheets,
)

BLUEPRINTS = (
    fleet.bp,
    environment.bp,
    flights.bp,
    load_plans.bp,
    distribution.bp,
    cargo.bp,
    sheets.bp,
    audits.bp,
    clock_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        error_id = "ERR_NOT_FOUND" if exc.code == 404 else "ERR_INVALID_REQUEST"
        return response.error_response(error_id, exc.description, exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
