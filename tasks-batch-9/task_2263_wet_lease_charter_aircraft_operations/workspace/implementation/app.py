"""Wet-lease / ACMI charter aircraft operations API — Flask application entrypoint.

Storage is in-memory only.  Nothing is seeded: every boot starts with thirteen
empty dictionaries and a logical clock reading 2026-08-01T00:00:00Z.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, DEFAULT_MESSAGES  # noqa: E402
from response import error_response  # noqa: E402

from routes.parties import bp as parties_bp  # noqa: E402
from routes.leases import bp as leases_bp  # noqa: E402
from routes.approvals import bp as approvals_bp  # noqa: E402
from routes.insurance import bp as insurance_bp  # noqa: E402
from routes.qualifications import bp as qualifications_bp  # noqa: E402
from routes.legs import bp as legs_bp  # noqa: E402
from routes.substitutions import bp as substitutions_bp  # noqa: E402
from routes.billing import bp as billing_bp  # noqa: E402
from routes.reliability import bp as reliability_bp  # noqa: E402
from routes.returns import bp as returns_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402

BLUEPRINTS = (
    parties_bp,
    leases_bp,
    approvals_bp,
    insurance_bp,
    qualifications_bp,
    legs_bp,
    substitutions_bp,
    billing_bp,
    reliability_bp,
    returns_bp,
    clock_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested path does not exist.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed for this path.", 405)
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", DEFAULT_MESSAGES["ERR_INVALID_REQUEST"], 400)
        if exc.code and exc.code >= 500:
            return error_response("ERR_INTERNAL", "Internal server error.", 500)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Invalid request.", exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
