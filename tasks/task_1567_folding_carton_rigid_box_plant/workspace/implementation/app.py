"""Folding-Carton & Rigid-Box Plant API — Flask entry point."""

import os
import traceback

from flask import Flask, request

import db
from errors import ApiError, ERR_INTERNAL, ERR_NOT_FOUND
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_store_lock():
        # Mutations apply atomically within the triggering request (PRD §2.10).
        if request.method != "GET":
            db.lock.acquire()

    @app.teardown_request
    def _release_store_lock(_exc):
        if request.method != "GET" and db.lock.locked():
            db.lock.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        traceback.print_exc()
        return error_response(ApiError(ERR_INTERNAL, 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
