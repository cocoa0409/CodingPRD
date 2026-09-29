"""Sales Tax Audit, Assessment and Appeal API — Flask entry point.

Storage is in-memory only and nothing is seeded at start-up: every test builds
its own state through the API.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, ERROR_STATUS
from response import error_response
from routes import (
    adjustments,
    appeals,
    arrangements,
    assessments,
    audits,
    certificates,
    clock,
    projects,
    sampling,
    taxpayers,
    usetax,
    waivers,
)

BLUEPRINTS = (
    taxpayers.bp,
    projects.bp,
    audits.bp,
    waivers.bp,
    sampling.bp,
    certificates.bp,
    usetax.bp,
    assessments.bp,
    adjustments.bp,
    appeals.bp,
    arrangements.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        status = getattr(exc, "code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return error_response("ERR_INVALID_REQUEST", str(exc), status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
