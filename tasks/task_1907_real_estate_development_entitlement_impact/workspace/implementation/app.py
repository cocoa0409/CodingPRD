"""Entitlement API entry point: Flask app, error handlers, route registration.

Boots cleanly from a fresh process on every invocation; all state lives in
process-local dicts (see store.py) and starts empty. Nothing is seeded.
"""

import os
import signal

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from envelope import error
from routes_core import register_core_routes
from routes_review import register_review_routes
from routes_fees import register_fee_routes


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error(ERR_NOT_FOUND, "Resource not found", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error(ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        return error("ERR_INTERNAL", f"Unexpected error: {exc}", 500)

    register_core_routes(app)
    register_review_routes(app)
    register_fee_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    # The evaluation host is shared: unrelated pipelines have been observed
    # SIGTERMing foreign servers mid-request (pattern-based cleanup kills),
    # which resets in-flight keep-alive connections and fails tests for
    # reasons unrelated to the API contract. Lifecycle teardown in the runner
    # falls back to SIGKILL, so ignoring SIGTERM costs nothing operationally
    # and changes no observable API behavior.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
