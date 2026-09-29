"""Public Procurement Protest & Debarment API.

Flask application factory and error handling. All state lives in process memory
(see store.py); nothing is persisted to disk and no data is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ERROR_CATALOG, ApiError
from routes import (
    awards, bids, clock, debarment, hearings, protests, screenings, solicitations,
    vendors,
)

BLUEPRINTS = (
    clock.bp,
    vendors.bp,
    solicitations.bp,
    bids.bp,
    awards.bp,
    protests.bp,
    hearings.bp,
    debarment.bp,
    screenings.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "no such route", 404
            )
        if exc.code == 405:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "method not allowed for this route", 405
            )
        if exc.code in (400, 415):
            return envelope.error_response(
                "ERR_INVALID_REQUEST", exc.description or "malformed request", 400
            )
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error", exc_info=exc)
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "unexpected server error", 500
        )

    return app


app = create_app()

if __name__ == "__main__":
    assert ERROR_CATALOG  # the catalogue must be loaded before serving
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
