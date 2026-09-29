"""Carbon Sequestration Project Permitting and Storage Operations API.

Flask application factory and process entry point.  All state lives in the
in-memory dictionaries of ``db.py``; nothing is persisted and nothing is seeded,
so every fresh process starts completely empty with the logical clock at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import clock
import db
import response
from errors import ERROR_HTTP, ApiError
from routes import (
    claims,
    clock_routes,
    instruments,
    models,
    permits,
    plans,
    projects,
    remediation,
    tracts,
    wellbores,
)

BLUEPRINTS = (
    projects.bp,
    models.bp,
    wellbores.bp,
    tracts.bp,
    permits.bp,
    plans.bp,
    instruments.bp,
    claims.bp,
    remediation.bp,
    clock_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    db.reset()
    clock.reset()

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _start_request():
        # One version bump per row per request (PRD Section 2.8).
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif exc.code == 400:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        status = exc.code or ERROR_HTTP.get(error_id, 500)
        return response.error_response(error_id, exc.description or error_id, status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response("ERR_INTERNAL", "internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
