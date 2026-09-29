"""Flask application factory and entrypoint.

The whole store lives in memory (see db.py); a fresh process therefore starts
with an empty world and a logical clock reading exactly 2026-08-01T00:00:00Z.
Nothing is seeded, preloaded or persisted anywhere.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    bookings,
    chains,
    claims,
    donors,
    evaluations,
    followups,
    programs,
    recipients,
    reviews,
)

BLUEPRINTS = (
    programs.bp,
    recipients.bp,
    donors.bp,
    evaluations.bp,
    chains.bp,
    bookings.bp,
    followups.bp,
    reviews.bp,
    claims.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "malformed request", 400)
        return error_response(
            "ERR_INTERNAL", exc.description or "request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
