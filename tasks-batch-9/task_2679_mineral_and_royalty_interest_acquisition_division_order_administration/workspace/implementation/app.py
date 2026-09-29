"""Mineral Royalty Acquisition & Division Order Administration API.

Entry point: blueprint registration, the error envelope and the listener.
The in-memory store starts completely empty on every boot - nothing is seeded,
preloaded or hardcoded, because the harness relaunches this process before
every single test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, message_for
from routes import (clock, defects, dorders, interests, offers, owners, psas,
                    suspense, tracts, units)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (tracts, owners, interests, offers, psas, defects, units,
                   dorders, suspense, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error("ERR_INVALID_REQUEST", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error("ERR_INVALID_REQUEST",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST",
                                  message_for("ERR_INVALID_REQUEST"), 400)
        return response.error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return response.error("ERR_INVALID_REQUEST", "Unexpected server error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
