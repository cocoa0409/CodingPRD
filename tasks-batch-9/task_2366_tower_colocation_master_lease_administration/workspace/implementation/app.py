"""Tower Colocation Master Lease API.

A single Flask process holding all state in memory.  Nothing is seeded: every
collection starts empty on each cold boot and the logical clock starts at the
fixed default 2026-08-01T00:00:00Z.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402
from routes import register_routes  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "Method not allowed on this route.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
