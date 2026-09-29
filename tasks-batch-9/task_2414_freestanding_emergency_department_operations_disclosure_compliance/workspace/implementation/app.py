"""Freestanding Emergency Department Compliance API.

In-memory only: every entity lives in a plain dict inside `db.Store` and dies
with the process. Nothing is seeded, preloaded or persisted anywhere.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402
from routes.arrangements import bp as arrangements_bp  # noqa: E402
from routes.claims import bp as claims_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402
from routes.contracts import bp as contracts_bp  # noqa: E402
from routes.coverage import bp as coverage_bp  # noqa: E402
from routes.encounters import bp as encounters_bp  # noqa: E402
from routes.facilities import bp as facilities_bp  # noqa: E402
from routes.templates import bp as templates_bp  # noqa: E402
from routes.transfer_orders import bp as transfer_orders_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (
        facilities_bp,
        templates_bp,
        contracts_bp,
        coverage_bp,
        arrangements_bp,
        encounters_bp,
        transfer_orders_bp,
        claims_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path", 405
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "Request body or query parameters are malformed", 400
            )
        return error_response(
            "ERR_INTERNAL", exc.description or "Internal server error", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
