"""aegis-cnp-fraud: card-not-present fraud prevention API.

Boots with completely empty in-memory collections: nothing is seeded, preloaded
or read from disk, and the logical clock starts at 2026-08-01T00:00:00Z.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from errors import ApiError  # noqa: E402
from response import error  # noqa: E402
from routes import BLUEPRINTS  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)
        if exc.code in (400, 415):
            return error("ERR_VALIDATION", "Request body failed field-level validation", 422)
        return error(
            "ERR_INTERNAL", exc.description or "Request could not be processed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error("ERR_INTERNAL", "Unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
