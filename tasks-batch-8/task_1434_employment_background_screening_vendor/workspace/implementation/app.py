"""Employment Background Screening API — Flask entry point.

In-memory only: all state lives in module-level dicts in db.py. Nothing is
seeded at startup; every entity is created through the declared API surface.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID
from response import error_body
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_body(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_body(ERR_NOT_FOUND, "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return error_body(ERR_INVALID, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
