"""Mattress Recycling Program Administration API — Flask application entrypoint.

Boots a completely empty in-memory store on every process start: no entity data
is seeded, preloaded or hardcoded anywhere.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes import (haulers, pickup_orders, programs, rate_schedules,  # noqa: E402
                    recyclers, remittances, sites, take_back)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (programs, rate_schedules, remittances, sites, haulers,
                   recyclers, pickup_orders, take_back):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this path.", 405)
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST",
                                  "Malformed request.", 400)
        return response.error("ERR_INTERNAL", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error: %s", exc)
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
