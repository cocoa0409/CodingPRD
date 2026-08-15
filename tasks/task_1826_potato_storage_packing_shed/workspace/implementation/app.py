"""Entry point: Flask app, error handlers, blueprint registration.

All state is in-memory (store.py) and starts empty on every boot; the harness
restarts the server via start.sh before every test (per-test-server isolation).
"""
import os
import signal

from flask import Flask

from util import ApiError, error_response
from views import bp

# Robustness for the shared test host: the isolation harness's per-test
# restarts and round-end cleanup both terminate this process exclusively via
# SIGKILL (port-scoped kill), while unrelated activity on the shared host can
# deliver a spurious SIGTERM mid-request (observed as "connection reset by
# peer" flakes). SIGTERM carries no shutdown contract here, so ignore it.
signal.signal(signal.SIGTERM, signal.SIG_IGN)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", 404, "route not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", 405, "method not allowed")
        )

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", 500, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
