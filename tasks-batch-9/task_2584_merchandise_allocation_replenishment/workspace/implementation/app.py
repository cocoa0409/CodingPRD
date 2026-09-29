"""Merchandise Allocation & Replenishment API (Flask).

State lives entirely in process memory (see store.py): nothing is seeded and
nothing is persisted, so every fresh boot starts from an empty database.
"""
import os
import threading

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope as env
import routes_assortment
import routes_catalog
import routes_positions
import routes_promo
import routes_runs
import routes_transfers
from errors import ApiError


class Serialize:
    """Handle one request at a time: the store is plain dicts, not a database."""

    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            result = self.app(environ, start_response)
            return list(result)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for module in (
        routes_catalog,
        routes_positions,
        routes_runs,
        routes_promo,
        routes_transfers,
        routes_assortment,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return env.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return env.error_response(
                "ERR_INVALID_REQUEST", "No such resource path.", 404
            )
        if exc.code == 405:
            return env.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this path.", 405
            )
        if exc.code in (400, 415):
            return env.error_response(
                "ERR_INVALID_REQUEST",
                "The request body or query parameters are malformed.",
                400,
            )
        return env.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return (
            jsonify(
                {
                    "meta": env._meta(),
                    "response_type": "error",
                    "data": {
                        "error_id": "ERR_INTERNAL",
                        "message": "%s: %s" % (type(exc).__name__, exc),
                    },
                }
            ),
            500,
        )

    app.wsgi_app = Serialize(app.wsgi_app)
    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
