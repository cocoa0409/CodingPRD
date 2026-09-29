"""Recruitment Marketing & Employer Brand Program API.

Boots a fresh, empty in-memory store on every process start; no data is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (applications, community, core, flights, ledger, personas,
                    postings, presences, reviews)

BLUEPRINTS = (core.bp, personas.bp, postings.bp, flights.bp, applications.bp,
              community.bp, reviews.bp, presences.bp, ledger.bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.fail(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.fail("ERR_RECORD_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return response.fail("ERR_METHOD_NOT_ALLOWED",
                                 "Method not allowed on this resource.", 405)
        if exc.code == 400:
            return response.fail("ERR_INVALID_REQUEST",
                                 exc.description or "Malformed request.", 422)
        return response.fail("ERR_INTERNAL", exc.description or "Unexpected error.",
                             exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return response.fail("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
