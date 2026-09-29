"""Regional Climate Adaptation & Resilience Planning API -- entry point.

Storage is in-memory only (plain dicts in store.py). Nothing is seeded, preloaded
or hardcoded: the process boots with every collection empty and the logical clock
at 2026-08-01T00:00:00Z, and all state is created through the API.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError

from routes import aid as aid_routes
from routes import analyses as analyses_routes
from routes import assessments as assessments_routes
from routes import assets as assets_routes
from routes import clock as clock_routes
from routes import endorsements as endorsements_routes
from routes import hazards as hazards_routes
from routes import jurisdictions as jurisdictions_routes
from routes import links as links_routes
from routes import plan_cycles as plan_cycles_routes
from routes import programs as programs_routes
from routes import project_ops as project_ops_routes
from routes import projects as projects_routes
from routes import sessions as sessions_routes

BLUEPRINTS = (
    jurisdictions_routes.bp,
    plan_cycles_routes.bp,
    hazards_routes.bp,
    assets_routes.bp,
    assessments_routes.bp,
    projects_routes.bp,
    links_routes.bp,
    analyses_routes.bp,
    programs_routes.bp,
    project_ops_routes.bp,
    sessions_routes.bp,
    endorsements_routes.bp,
    aid_routes.bp,
    clock_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope.error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return envelope.error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this resource.", 405
            )
        if exc.code in (400, 415):
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "The request payload is malformed.", 422
            )
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be processed.",
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return envelope.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
