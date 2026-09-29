"""Cosmetics Facility Registration & Product Listing API.

Flask application factory and error plumbing.  All state lives in process memory
(see store.py); nothing is seeded, so every fresh boot starts empty with the
logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, jsonify

import envelope
import store
from errors import ApiError
from routes import (
    events,
    facilities,
    listings,
    ops,
    persons,
    recalls,
    substantiations,
)

BLUEPRINTS = (
    facilities.bp,
    persons.bp,
    listings.bp,
    substantiations.bp,
    events.bp,
    recalls.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        # Per-request bookkeeping: a resource touched by several cascade hops of
        # one request still rises by exactly one version (PRD §2.4).
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return envelope.error_response(ApiError("ERR_NOT_FOUND", "No such route."))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return envelope.error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route."))

    @app.errorhandler(400)
    def _bad_request(_err):
        return envelope.error_response(
            ApiError("ERR_INVALID_REQUEST", "The request body could not be read."))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err)
        return envelope.error_response(ApiError("ERR_INTERNAL", "Unexpected server error."))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
