"""Carpet mill fiber-extrusion API — Flask application factory and entry point.

All state lives in memory (see db.py).  Nothing is seeded at startup: every
entity is created through the declared endpoints.
"""

import os

from flask import Flask

from errors import ApiError
from response import error
from routes import (
    accounts,
    clock,
    dyelots,
    fiber,
    orders,
    polymer,
    rollgoods,
    runs,
    styles,
    tests_certs,
)

BLUEPRINTS = (
    accounts.bp,
    polymer.bp,
    fiber.bp,
    styles.bp,
    runs.bp,
    dyelots.bp,
    rollgoods.bp,
    tests_certs.bp,
    orders.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "The requested resource does not exist", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this path", 405
        )

    @app.errorhandler(400)
    def _bad_request(exc):
        return error(
            "ERR_INVALID_REQUEST", "The request body or query string is malformed", 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error("ERR_INTERNAL", str(exc) or "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
