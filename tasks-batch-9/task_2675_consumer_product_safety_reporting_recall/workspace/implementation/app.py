"""Consumer Product Safety Reporting & Recall API.

Entry point: registers every blueprint, installs the envelope-shaped error
handlers, and serves on 0.0.0.0:$PORT.  The store is in-memory and starts
completely empty on every boot - nothing is seeded here.
"""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import responses
from errors import ERROR_STATUS, ApiError
from routes import (claims, clock, evaluations, incidents, notices,
                    notifications, patterns, penalty, progress, recalls,
                    registry, reports, visits)

API_PREFIX = "/product-safety"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    for module in (registry, incidents, patterns, evaluations, reports, recalls,
                   notifications, visits, notices, claims, progress, penalty):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return responses.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return responses.error_response(
            "ERR_INVALID_REQUEST",
            "The request could not be routed or was malformed.",
            ERROR_STATUS["ERR_INVALID_REQUEST"])

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc(file=sys.stderr)
        return responses.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
