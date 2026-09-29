"""Neurodiagnostic / Long-Term EEG Monitoring Unit API.

A single Flask process holding every record in memory.  Nothing is seeded and
nothing is persisted: a fresh boot starts with fifteen empty collections and a
logical clock pinned to 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ERROR_HTTP, ApiError

# Importing the route modules registers every rule on the shared blueprint.
import routes_infrastructure  # noqa: F401
import routes_authorization  # noqa: F401
import routes_admission  # noqa: F401
import routes_study  # noqa: F401
import routes_event  # noqa: F401
import routes_report  # noqa: F401
import routes_conference  # noqa: F401
from web import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.send(
            response.error_body(error.error_id, error.message), error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif error.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif error.code in (400, 415):
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        status = ERROR_HTTP.get(error_id, error.code or 500)
        return response.send(
            response.error_body(error_id, error.description or error_id), status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return response.send(
            response.error_body("ERR_INTERNAL", str(error) or "Internal error."), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
