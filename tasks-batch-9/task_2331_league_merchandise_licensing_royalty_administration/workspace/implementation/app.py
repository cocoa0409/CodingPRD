"""League Merch Licensing API -- Flask application factory and entry point.

Storage is in-memory only and starts completely empty on every boot; nothing is
ever seeded, preloaded or persisted.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (agreements, audits, catalog, distributions, enforcement, licensees,
                    ops, reports, retailers, submissions)

BLUEPRINTS = (
    catalog.bp,
    licensees.bp,
    agreements.bp,
    submissions.bp,
    retailers.bp,
    reports.bp,
    audits.bp,
    enforcement.bp,
    distributions.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error("ERR_NOT_FOUND", "No such resource.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error("ERR_VALIDATION", "Malformed request.", 422)
        return response.error("ERR_VALIDATION", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
