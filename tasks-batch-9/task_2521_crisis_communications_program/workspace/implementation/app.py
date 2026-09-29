"""Crisis Communications Program API - Flask application entry point.

Storage is in-memory only (plain Python dicts inside core.Store). Nothing is
seeded, preloaded or persisted: every entity is created by clients through the
declared endpoints, and a fresh process always starts with twelve empty
collections and the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_claim
import routes_incident
import routes_interview
import routes_notice
import routes_registry
import routes_statement
import routes_team


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_incident.bp)
    app.register_blueprint(routes_team.bp)
    app.register_blueprint(routes_statement.bp)
    app.register_blueprint(routes_notice.bp)
    app.register_blueprint(routes_interview.bp)
    app.register_blueprint(routes_claim.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        wrapper = ApiError.__new__(ApiError)
        Exception.__init__(wrapper, exc.name)
        wrapper.error_id = "ERR_INVALID_REQUEST" if exc.code == 400 else "ERR_NOT_FOUND"
        if exc.code == 405:
            wrapper.error_id = "ERR_METHOD_NOT_ALLOWED"
        wrapper.http_status = exc.code or 500
        wrapper.message = exc.description or exc.name
        return error_response(wrapper)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        wrapper = ApiError.__new__(ApiError)
        Exception.__init__(wrapper, str(exc))
        wrapper.error_id = "ERR_INTERNAL"
        wrapper.http_status = 500
        wrapper.message = str(exc)
        return error_response(wrapper)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
