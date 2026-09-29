"""Pilgrimage Group Travel Operations API.

A single Flask process holding all state in module-level Python dictionaries.
Nothing is persisted and nothing is seeded: every row in every collection is
created by a client through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (advisories, agreements, air_blocks, clock, departures, finance, land,
                   pilgrims, programs, protections, sites)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (clock, programs, departures, agreements, pilgrims, finance, air_blocks,
                   sites, land, protections, advisories):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return response.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Malformed request body.", 400)
        return response.error("ERR_INVALID_REQUEST", exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return response.error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
