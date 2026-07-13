"""Drone BVLOS Delivery API — entry point.

The in-memory store starts empty on every boot. No entity is seeded.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes.admin import bp as admin_bp
from routes.fleet import bp as fleet_bp
from routes.flights import bp as flights_bp
from routes.geography import bp as geography_bp
from routes.incidents import bp as incidents_bp
from routes.orders import bp as orders_bp


class SerializedRequests:
    """Every request runs under one lock: multi-step mutations stay atomic."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.wsgi_app = SerializedRequests(app.wsgi_app)

    for bp in (admin_bp, geography_bp, fleet_bp, orders_bp, flights_bp, incidents_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code in (400, 415):
            return error("ERR_INVALID_REQUEST", "The request payload is invalid.", 422)
        return error("ERR_INTERNAL", exc.description or "Error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
