"""Entry point: Flask app assembly, error handlers, route registration.

Storage is in-memory only (db.py dicts); nothing is seeded at startup.
Listens on 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_envelope


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False

    from routes import (
        tours, markets, venues, legs, shows, holds, packets,
        budget, marketing, settlements, compliance, clock,
    )

    for module in (
        tours, markets, venues, legs, shows, holds, packets,
        budget, marketing, settlements, compliance, clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_envelope(e.error_id, e.message, e.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        if e.code == 404:
            return error_envelope("ERR_NOT_FOUND", "Path resource does not exist", 404)
        return error_envelope("ERR_INVALID_REQUEST", e.name, e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_envelope("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
