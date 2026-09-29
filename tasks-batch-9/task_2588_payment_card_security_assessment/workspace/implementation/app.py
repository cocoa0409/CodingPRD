"""Payment card security assessment API — application factory and entry point.

Storage is process-local and in-memory only (see db.Store); a fresh process
starts with every collection empty and no seeded rows of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import ccws, engagements, registry, requirements, rocs, sampling, scans, segments

BLUEPRINTS = (
    registry.bp,
    engagements.bp,
    segments.bp,
    sampling.bp,
    requirements.bp,
    ccws.bp,
    rocs.bp,
    scans.bp,
)


def create_app():
    app = Flask(__name__)
    # Field order is contractual: stratum_allocations must keep the pinned
    # stratum order, so JSON keys are never re-sorted alphabetically.
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_body("ERR_INVALID_REQUEST", "The requested route does not exist."), 404
        if exc.code == 405:
            return error_body("ERR_INVALID_REQUEST",
                              "The method is not allowed for this route."), 405
        if exc.code and exc.code < 500:
            return error_body("ERR_INVALID_REQUEST",
                              "The request body or query string is malformed."), 400
        return error_body("ERR_INTERNAL", "Unexpected server error."), 500

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_body("ERR_INTERNAL", "Unexpected server error."), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
