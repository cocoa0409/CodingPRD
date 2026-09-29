"""Offsite Modular Construction — Factory-to-Site Set Coordination API.

Flask application factory and process entry point. All state lives in memory
(see store.py); nothing is seeded, persisted or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import claims, clock, design, draws, inspections, modules
from routes import permits, projects, registry, shipments


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        registry.bp,
        projects.bp,
        design.bp,
        modules.bp,
        permits.bp,
        inspections.bp,
        shipments.bp,
        claims.bp,
        draws.bp,
        clock.bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "unknown resource path", 404)
            )
        if err.code == 405:
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "method not allowed", 405)
            )
        if err.code in (400, 415):
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "malformed request", 400)
            )
        return error_response(
            ApiError("ERR_INVALID_REQUEST", err.description or "request failed", err.code or 400)
        )

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "internal error: %s" % err, 500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
