"""Pentest Assurance API entry point.

All state lives in process memory and starts empty on every boot: nothing is
seeded, preloaded or hardcoded.  Every record is created by a client through the
declared endpoints.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ERROR_STATUS, ApiError
from routes import (
    alerts,
    assets,
    assignments,
    clock,
    engagements,
    findings,
    plans,
    remediations,
    retests,
    roe,
    scope,
    testers,
)

PREFIXED = (
    assets.bp,
    plans.bp,
    scope.bp,
    engagements.bp,
    roe.bp,
    testers.bp,
    assignments.bp,
    findings.bp,
    alerts.bp,
    remediations.bp,
    retests.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in PREFIXED:
        app.register_blueprint(blueprint, url_prefix="/pentest")
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(error):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return error_response(
            "ERR_NOT_FOUND", "The requested method is not allowed for this resource.", 404
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
