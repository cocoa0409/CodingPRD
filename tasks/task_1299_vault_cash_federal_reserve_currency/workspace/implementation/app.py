"""Entry point: Flask app, error handlers, route registration."""
import os
import signal

from flask import Flask

from errors import ApiError
from response import err
from routes import register_routes


def _sigterm_exit(signum, frame):
    # Die immediately on SIGTERM: the per-test-server harness stops and respawns
    # the server before every test. werkzeug's graceful shutdown can linger for
    # seconds on an open keep-alive connection, which stalls the restart cycle
    # and surfaces as spurious "could not be restarted" timeouts. State is
    # in-memory only, so an immediate exit loses nothing.
    os._exit(0)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_INVALID_REQUEST", 400, "Referenced resource does not exist")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_INVALID_REQUEST", 400, "Referenced resource does not exist")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _sigterm_exit)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
