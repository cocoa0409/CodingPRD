"""Biometric Privacy Consent Program API.

In-memory only: every process start begins with an empty store and a logical
UTC clock pinned to 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError
import routes_asset
import routes_consent
import routes_core
import routes_incident
import routes_policy
import routes_vendor


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_vendor.bp)
    app.register_blueprint(routes_policy.bp)
    app.register_blueprint(routes_asset.bp)
    app.register_blueprint(routes_consent.bp)
    app.register_blueprint(routes_incident.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_PROGRAM_NOT_FOUND", "No such resource.", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST", "Method not allowed for this path.", 400)
        if exc.code in (400, 415):
            return error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
