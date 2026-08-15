"""Flatbed Heavy Haul API — Flask entry point.

The store is pure in-memory module state; every process boot starts empty.
"""
import os

from flask import Flask, jsonify

from store import store
from helpers import ApiError, error_payload, ERR_NOT_FOUND
import routes_core
import routes_children


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_payload(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_payload(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_payload(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        import traceback
        traceback.print_exc()
        return jsonify(error_payload("ERR_INTERNAL", "Internal server error")), 500

    # Serialize request handling so cascades and OCC checks are atomic.
    @app.before_request
    def acquire_lock():
        store.lock.acquire()

    @app.teardown_request
    def release_lock(exc=None):
        store.lock.release()

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_children.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
