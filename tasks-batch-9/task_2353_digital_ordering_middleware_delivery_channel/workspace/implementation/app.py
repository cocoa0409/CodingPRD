"""Digital Ordering Middleware API — application factory and entry point.

Storage is in-memory only and starts completely empty on every boot: no
entity is seeded, preloaded or hardcoded anywhere in this package.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from errors import ApiError
from routes import (adjustments, assignments, availability, channels,
                    clock_routes, listings, menu_versions, networks, orders,
                    statements, stores)

BLUEPRINTS = (
    clock_routes.bp,
    stores.bp,
    channels.bp,
    menu_versions.bp,
    listings.bp,
    availability.bp,
    orders.bp,
    networks.bp,
    assignments.bp,
    adjustments.bp,
    statements.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "The method is not allowed for the requested URL.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error_response(
                errors.ERR_INVALID_REQUEST, "The request could not be parsed.", 400)
        return response.error_response(
            "ERR_HTTP_ERROR", exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return response.error_response(
            "ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
