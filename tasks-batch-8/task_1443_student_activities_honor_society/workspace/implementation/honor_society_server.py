"""NHS Chapter Management API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
The server binds 0.0.0.0:$PORT (default 10000) and runs in the foreground.
"""

import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, f"Internal error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
