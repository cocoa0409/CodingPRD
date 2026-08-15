"""Entry point: Flask app, error handlers, route registration.

The store is in-memory and starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

from db import store
from errors import ApiError
from respond import error
from routes import ALL_BLUEPRINTS

API_PREFIX = "/bulk-liquid"


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False

    @app.before_request
    def _acquire_store_lock():
        store.lock.acquire()

    @app.teardown_request
    def _release_store_lock(exc=None):
        store.lock.release()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error("ERR_NOT_FOUND", "Resource not found", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INTERNAL", "Internal server error", 500)

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
