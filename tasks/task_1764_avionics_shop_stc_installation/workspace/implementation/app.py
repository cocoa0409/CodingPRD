"""Avionics Shop STC API — Flask entry point.

In-memory store; boots empty on every launch (no seeding). Reads PORT
(default 10000), binds 0.0.0.0, runs in the foreground under start.sh.
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return response.error("ERR_VALIDATION", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.error("ERR_INTERNAL", f"Unexpected server error: {e}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
