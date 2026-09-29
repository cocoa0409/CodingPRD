"""Cell Tower Ground Lease Buyout API.

Boots empty on every process start: all state lives in module-level dicts inside
db.py, nothing is seeded, and nothing is persisted anywhere.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import engine
from errors import CATALOG, ApiError
from response import error
from routes import BLUEPRINTS

API_PREFIX = "/lease-buyouts"


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.before_request
    def _sweep():
        """Lazy expiry: every request first materialises whatever the logical
        clock implies (offer lapse, consent expiry, refusal-window lapse) so no
        caller can ever observe a stale non-expired state."""
        if request.path.startswith(API_PREFIX):
            engine.sweep_expiries()
        return None

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            spec = CATALOG["ERR_NOT_FOUND"]
            return error("ERR_NOT_FOUND", spec[1], 404)
        if exc.code == 405:
            return error("ERR_NOT_FOUND", "Method not allowed for this resource.", 404)
        if exc.code in (400, 415):
            spec = CATALOG["ERR_INVALID_REQUEST"]
            return error("ERR_INVALID_REQUEST", spec[1], 400)
        return error("ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
