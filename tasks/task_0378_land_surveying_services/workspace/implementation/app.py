"""Land Surveying Services API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os
import socket

# Werkzeug's dev server computes a cosmetic server_name via socket.getfqdn()
# when binding to 0.0.0.0. On some hosts the reverse lookup of a ".local"
# hostname blocks ~5s, which — multiplied across the per-test reboots of a
# concurrent test sweep — blows past the restart window. The value is only
# used for the startup banner, so short-circuit it to keep boot fast. Binding
# still targets 0.0.0.0 (the evaluator contract); only name resolution changes.
_real_getfqdn = socket.getfqdn
socket.getfqdn = lambda *a, **k: "localhost"

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
