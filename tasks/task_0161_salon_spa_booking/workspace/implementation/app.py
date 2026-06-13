"""Salon & Spa Booking API — Flask entry point.

In-memory only; no seeding at startup. The store (db.py module dicts) begins
empty on every fresh process. start.sh re-launches this process before every
per-test run, wiping all state.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import success, error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        return body, exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path. Surface as ERR_NOT_FOUND in the standard envelope.
        body = error_response("ERR_NOT_FOUND", "resource not found")
        return body, 404

    @app.errorhandler(405)
    def handle_405(exc):
        body = error_response("ERR_NOT_FOUND", "method not allowed")
        return body, 404

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Let real HTTP exceptions (already handled above) pass through; any
        # other uncaught error becomes a generic invalid-request rather than a
        # bare 500 HTML page, keeping the envelope consistent.
        if isinstance(exc, HTTPException):
            body = error_response("ERR_INVALID_REQUEST", exc.description or "bad request")
            return body, exc.code if exc.code and exc.code < 500 else 400
        body = error_response("ERR_INVALID_REQUEST", "unexpected server error")
        return body, 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
