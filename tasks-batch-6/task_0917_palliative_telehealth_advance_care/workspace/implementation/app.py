"""Palliative Telehealth and Advance-Care Planning API.

Entry point: registers every blueprint, installs the error handlers that render
the standard error envelope, and boots an empty in-memory store (no seeding).
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from envelope import error_body  # noqa: E402
from errors import (  # noqa: E402
    ERR_RESOURCE_NOT_FOUND, ERR_VALIDATION, ApiError, HTTP_STATUS,
)
from routes.careplans import bp as careplans_bp  # noqa: E402
from routes.claims import bp as claims_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402
from routes.conferences import bp as conferences_bp  # noqa: E402
from routes.dme import bp as dme_bp  # noqa: E402
from routes.documents import bp as documents_bp  # noqa: E402
from routes.hospice import bp as hospice_bp  # noqa: E402
from routes.medications import bp as medications_bp  # noqa: E402
from routes.patients import bp as patients_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (patients_bp, documents_bp, careplans_bp, conferences_bp,
                      medications_bp, dme_bp, hospice_bp, claims_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code in (404, 405):
            return error_body(ERR_RESOURCE_NOT_FOUND, "The requested resource does not exist.",
                              HTTP_STATUS[ERR_RESOURCE_NOT_FOUND])
        if exc.code in (400, 415):
            return error_body(ERR_VALIDATION, "The request could not be parsed.",
                              HTTP_STATUS[ERR_VALIDATION])
        return error_body(ERR_VALIDATION, exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_body(ERR_VALIDATION, "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
