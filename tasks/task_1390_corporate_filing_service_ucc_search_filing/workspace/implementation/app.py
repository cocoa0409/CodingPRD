"""Corporate Filing & UCC Search API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot; the
logical clock starts at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

import db
from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Route not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        import traceback
        traceback.print_exc()
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    # Serialize requests through one store lock so concurrent traffic observes
    # immediate consistency. teardown_request always runs, pairing the release.
    @app.before_request
    def _acquire_store():
        db.store.lock.acquire()

    @app.teardown_request
    def _release_store(_exc):
        try:
            db.store.lock.release()
        except RuntimeError:
            pass

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
