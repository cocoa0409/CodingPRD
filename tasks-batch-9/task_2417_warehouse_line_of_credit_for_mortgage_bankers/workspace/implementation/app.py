"""Warehouse line of credit for mortgage bankers — Flask application factory.

Storage is in-memory only and nothing is seeded: every collection starts empty
on every boot and all state is built through the declared endpoints.
"""

import os

from flask import Flask

from errors import ApiError
from response import error
from routes import (
    advances,
    clock_route,
    commitments,
    covenant_tests,
    custodians,
    demands,
    facilities,
    investors,
    margin_calls,
    receipts,
    wires,
)

BLUEPRINTS = (
    facilities.bp,
    custodians.bp,
    investors.bp,
    commitments.bp,
    advances.bp,
    wires.bp,
    receipts.bp,
    margin_calls.bp,
    covenant_tests.bp,
    demands.bp,
    clock_route.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error("ERR_NOT_FOUND", "No route matches the requested path.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error("ERR_METHOD_NOT_ALLOWED",
                     "The method is not allowed for the requested path.", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error("ERR_VALIDATION", "The request could not be parsed.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("Unhandled error: %s", exc)
        return error("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
