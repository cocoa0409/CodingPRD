"""Injection Molding Job Shop API — entry point.

Storage is in-memory only and starts completely empty on every boot; every
entity is created by a client through a declared endpoint.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_commercial
import routes_master
import routes_production
from common import ApiError, respond_error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    routes_master.register(app)
    routes_commercial.register(app)
    routes_production.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return respond_error(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return respond_error("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if err.code == 405:
            return respond_error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        return respond_error("ERR_INVALID_REQUEST", err.description or "Bad request.",
                             err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - safety net
        app.logger.exception("unhandled error")
        return respond_error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
