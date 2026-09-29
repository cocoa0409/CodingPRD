"""Battery Recycling, Second-Life Triage and Metal Recovery API.

Flask application factory and process entrypoint. All state lives in process memory
(see core.Store); nothing is persisted, cached on disk, seeded or preloaded, so a fresh
process always starts with fifteen empty collections and the logical clock parked at
2026-08-01T00:00:00.000Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_intake
import routes_recovery
import routes_settlement
from core import ApiError, error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_intake.bp)
    app.register_blueprint(routes_recovery.bp)
    app.register_blueprint(routes_settlement.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            wrapped = ApiError("ERR_INVALID_REQUEST", "Unknown resource path.")
            wrapped.status = 404
        elif err.code == 405:
            wrapped = ApiError("ERR_INVALID_REQUEST", "Method not allowed for this path.")
            wrapped.status = 405
        else:
            wrapped = ApiError("ERR_INVALID_REQUEST", err.description or "Bad request.")
            wrapped.status = err.code or 400
        return error_response(wrapped)

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        wrapped = ApiError("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err)
        wrapped.status = 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
