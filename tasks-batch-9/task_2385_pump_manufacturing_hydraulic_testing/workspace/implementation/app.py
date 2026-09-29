"""Pump Manufacturing and Hydraulic Testing API.

Boots a completely empty in-memory store on every process start: nothing is
seeded, so every entity a client needs is created through the declared
endpoints.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes
from db import db
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - Flask < 2.2
        pass

    for blueprint in routes.BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        # One request at a time: every handler mutates the shared store and the
        # per-entity "bump the version once" rule is scoped to the request.
        db.lock.acquire()
        g.touched = set()

    @app.teardown_request
    def _end(exception=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if error.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this resource", 405
            )
        if error.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "Request payload is malformed", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", error.description or "Request could not be processed",
            error.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(error):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
