"""Marketplace Fulfillment Inventory & Storage Cost API.

Flask application factory and entrypoint. All state lives in process memory
(see db.py) and the store is empty on every boot — nothing is ever seeded.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import db as store
import middleware
import response
from errors import ApiError
from routes import (centers, claims, listings, lots, ops, orders, plans,
                    removals, sellers)

BLUEPRINTS = (
    sellers.bp,
    centers.bp,
    listings.bp,
    plans.bp,
    lots.bp,
    removals.bp,
    claims.bp,
    orders.bp,
    ops.bp,
)


class _SerializedRequests:
    """The store is a plain dict graph, so requests are handled one at a time.

    The server still runs threaded (keep-alive connections must not block one
    another), but every request body is processed under a single lock.
    """

    def __init__(self, wsgi_app):
        self._wsgi_app = wsgi_app
        self._lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self._lock:
            return list(self._wsgi_app(environ, start_response))


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        store.begin_request()
        middleware.authenticate()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The requested path does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("unhandled error")
        return response.error_response("ERR_INVALID_REQUEST", str(exc) or "Server error.", 500)

    app.wsgi_app = _SerializedRequests(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
