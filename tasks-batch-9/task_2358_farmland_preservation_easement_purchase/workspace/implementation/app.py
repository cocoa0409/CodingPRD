"""Farmland Preservation Easement Purchase API.

Flask application factory and entrypoint. Storage is process-local and
in-memory only (see db.py) and nothing is seeded, so every boot starts from an
empty store with the logical clock at its fixed default.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import (
    amendments,
    applications,
    appraisals,
    easements,
    funding,
    landowners,
    ops,
    parcels,
    programs,
    requirements,
    rounds,
    violations,
    visits,
)

BLUEPRINTS = (
    programs.bp,
    rounds.bp,
    landowners.bp,
    parcels.bp,
    applications.bp,
    appraisals.bp,
    funding.bp,
    requirements.bp,
    easements.bp,
    visits.bp,
    violations.bp,
    amendments.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_body("ERR_INVALID_REQUEST", "Resource not found"), 404
        if exc.code == 405:
            return (
                error_body("ERR_INVALID_REQUEST", "Method not allowed for this path"),
                405,
            )
        if exc.code in (400, 415):
            return (
                error_body("ERR_INVALID_REQUEST", "Request payload is invalid"),
                422,
            )
        return error_body("ERR_INVALID_REQUEST", exc.description or "Request failed"), (
            exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error: %s", exc)
        return error_body("ERR_INVALID_REQUEST", "Unexpected server error"), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
