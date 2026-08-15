"""Entry point: Flask app, error handlers, route registration.

The store starts completely empty on every boot; all state is built through
the declared API surface. The logical clock starts at 2026-08-01T00:00:00Z
(PRD §2.5).
"""

import os

from flask import Flask, jsonify

from helpers import ApiError, error_response
from store import db

import routes_core
import routes_orders
import routes_spots
import routes_logs


class _LockMiddleware:
    """Serialize every request through the store's global lock so concurrent
    writes (placements, approvals) resolve through the OCC guards rather than
    racing dict mutations."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with db.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_spots.bp)
    app.register_blueprint(routes_logs.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return (
            jsonify(
                {
                    "meta": {},
                    "response_type": "error",
                    "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
                }
            ),
            500,
        )

    app.wsgi_app = _LockMiddleware(app.wsgi_app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
