"""Outdoor Gear Repair & Warranty Program API -- application entry point.

Storage is in-memory only (plain Python dicts inside ``core.Store``) and starts
completely empty on every boot: no seeding, no preloading, no disk persistence.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
from routes.claims import bp as claims_bp
from routes.config import bp as config_bp
from routes.orders import bp as orders_bp
from routes.parts import bp as parts_bp
from routes.people import bp as people_bp

API_PREFIX = "/gear-service"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (config_bp, people_bp, parts_bp, claims_bp, orders_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found.", 404))
        if exc.code == 405:
            return error_response(
                ApiError("ERR_NOT_FOUND", "Method not allowed for this path.", 405)
            )
        if exc.code in (400, 415):
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "The request could not be parsed.", 422)
            )
        return error_response(
            ApiError("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
