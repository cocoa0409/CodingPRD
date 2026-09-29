"""Outfitter & Guide Special Use Permit Administration API (PRD /osup).

Flask app factory + global error handling.  All state lives in process memory
(see store.py); nothing is seeded at boot.
"""
import os

from flask import Flask, request

import envelope
import store
from errors import ApiError

MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes import BLUEPRINTS

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _begin_request():
        store.begin(request.method in MUTATING_METHODS)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        store.rollback()
        return envelope.error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        store.rollback()
        return envelope.error_response(ApiError("ERR_NOT_FOUND", "no such route"))

    @app.errorhandler(405)
    def _handle_405(_err):
        store.rollback()
        return envelope.error_response(
            ApiError("ERR_INVALID_REQUEST", "method not allowed for this path")
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return _handle_api_error(err)
        store.rollback()
        return envelope.error_response(ApiError("ERR_INTERNAL", str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
