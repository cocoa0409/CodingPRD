"""Utility & cargo trailer manufacturing API — Flask entrypoint.

State lives entirely in process memory (see db.py); nothing is persisted and
nothing is seeded, so every fresh boot starts from a completely empty plant.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from db import db
from response import error
from routes import (assets, claims, clock, dealers, labels, models, options,
                    orders, roadtests, units)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (clock, models, dealers, assets, units, options, roadtests,
                   labels, orders, claims):
        app.register_blueprint(module.bp)

    @app.before_request
    def _serialize_requests():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(errors.ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error("ERR_ROLE_NOT_PERMITTED", "Method not allowed for this path", 405)
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "Invalid request: malformed body", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed",
                     exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
