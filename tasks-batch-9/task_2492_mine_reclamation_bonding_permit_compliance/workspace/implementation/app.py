"""Application entry point.

State lives entirely in process memory (see db.py) and the store is empty on
every boot, so the harness can kill and relaunch this process before each test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    clock,
    estimates,
    forfeitures,
    inspections,
    inspector_profiles,
    instruments,
    mine_sites,
    notices,
    operators,
    permits,
    releases,
    revisions,
)

BLUEPRINTS = (
    operators.bp,
    mine_sites.bp,
    inspector_profiles.bp,
    permits.bp,
    estimates.bp,
    instruments.bp,
    releases.bp,
    inspections.bp,
    notices.bp,
    revisions.bp,
    forfeitures.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(error):
        return error_response(
            "ERR_NOT_FOUND", "The requested resource path does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this path.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        return error_response(
            "ERR_INVALID_REQUEST", error.description or "Malformed request.", error.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
