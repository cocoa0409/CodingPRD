"""Optical laboratory prescription fulfillment API.

Storage is in-memory only (plain Python dicts in store.py).  Every collection
starts empty on every boot; no entity data is ever seeded, preloaded or
hardcoded.  All state is built through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes.clock import bp as clock_bp
from routes.lab import bp as lab_bp
from routes.orders import bp as orders_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.registry import bp as registry_bp
from routes.remakes import bp as remakes_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(registry_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(lab_bp)
    app.register_blueprint(remakes_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "No such resource.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this path.", 405
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_VALIDATION",
                "The request body is malformed, is missing a required field, or carries an "
                "out-of-domain value.",
                400,
            )
        return error_response("ERR_VALIDATION", exc.description or "Request failed", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", str(exc) or "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
