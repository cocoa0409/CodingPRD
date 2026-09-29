"""Hospital Accreditation Survey Readiness & Corrective Action API.

Storage is in-memory only (plain dicts in store.py). Nothing is seeded: every
entity is created by a client through the declared endpoints.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from envelope import error_response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes import (  # noqa: E402
    chapters,
    clock,
    evidence,
    findings,
    ppr,
    rounding,
    standards,
    tracers,
    units,
    windows,
)

BLUEPRINTS = (
    chapters.bp,
    standards.bp,
    evidence.bp,
    units.bp,
    tracers.bp,
    rounding.bp,
    windows.bp,
    findings.bp,
    ppr.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request body is invalid.", 400)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405)

    @app.errorhandler(415)
    def _unsupported_media(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request body is invalid.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
