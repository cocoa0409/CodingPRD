"""Streaming Royalty Distribution API — Flask application entry point.

Storage is in-memory only and the store is created empty on every boot; no
entity data is ever seeded, preloaded or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    audits,
    clock,
    holders,
    periods,
    pools,
    rates,
    registrations,
    statements,
    usage,
    works,
)

BLUEPRINTS = (
    holders.bp,
    works.bp,
    periods.bp,
    usage.bp,
    registrations.bp,
    pools.bp,
    statements.bp,
    audits.bp,
    rates.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if status == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed for this path.", 405)
        if status == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", error.description or "Error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - safety net
        return error_response("ERR_INVALID_REQUEST", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
