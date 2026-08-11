"""Corporate Actions Desk API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only and starts
empty on every boot; the logical clock starts at 2026-05-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from helpers import error_response
import routes_setup
import routes_events
import routes_voluntary
import routes_recon


def create_app():
    app = Flask(__name__, static_folder=None)
    app.register_blueprint(routes_setup.bp)
    app.register_blueprint(routes_events.bp)
    app.register_blueprint(routes_voluntary.bp)
    app.register_blueprint(routes_recon.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response(ApiError("ERR_INTERNAL", 500, str(exc)))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
