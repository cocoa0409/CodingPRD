"""Blow Molding & Bottle Plant API — Flask entry point.

In-memory storage only (Python dicts, see db.py); the store starts empty on
every boot. All datetime comparisons read the logical plant clock
(default 2026-08-01T00:00:00Z) — never wall-clock time.
"""
import os

from flask import Flask

from errors import ApiError
from envelope import error_response
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404,
                              "The requested resource does not exist")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405,
                              "Method not allowed for this path")

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    register_all(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
