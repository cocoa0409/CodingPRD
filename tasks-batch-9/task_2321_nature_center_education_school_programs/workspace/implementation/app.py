"""Nature Center Education & School Programs API.

Flask application factory + entrypoint. All state lives in process memory
(see store.py); nothing is seeded at boot, so every fresh launch starts empty.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import logical_clock  # noqa: E402
from envelope import error_response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes.bookings import bp as bookings_bp  # noqa: E402
from routes.catalog import bp as catalog_bp  # noqa: E402
from routes.money import bp as money_bp  # noqa: E402
from routes.ops import bp as ops_bp, clock_bp  # noqa: E402
from routes.staff import bp as staff_bp  # noqa: E402
from routes.stewardship import bp as stewardship_bp  # noqa: E402

API_PREFIX = "/nature-center"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (catalog_bp, staff_bp, stewardship_bp, bookings_bp, money_bp, ops_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    app.register_blueprint(clock_bp)

    logical_clock.reset()

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400
            )
        return error_response(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
