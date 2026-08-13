"""Intercompany Transfer Pricing API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
no entities are seeded at startup.
"""
import os

from flask import Flask

from db import store
from errors import ApiError, NOT_FOUND
from response import error_envelope
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    # Serialize requests through a re-entrant lock so concurrent requests
    # during a single server lifetime observe immediate consistency.
    @app.before_request
    def _acquire_store():
        store.lock.acquire()

    @app.teardown_request
    def _release_store(exc):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    register_routes(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_envelope(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_envelope(NOT_FOUND, "The requested resource was not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_envelope(NOT_FOUND, "The requested resource was not found", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        return error_envelope("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
