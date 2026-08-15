"""Boatyard Haul-Out & Refit Management API. Entry point: Flask app, global
request lock, error handlers, route registration. The store starts empty on
every boot; nothing is seeded."""

import os

from flask import Flask, g

import db
import response
from errors import ApiError, ERR_NOT_FOUND
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _acquire_lock():
        db.lock.acquire()
        g._yard_lock_held = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_yard_lock_held", False):
            g._yard_lock_held = False
            db.lock.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return response.error(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return response.error(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(err):
        return response.error(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return response.error(ApiError("ERR_INTERNAL", 500, f"Internal error: {err}"))

    register_routes(app)

    @app.get("/")
    def root():
        return response.success_object({})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
