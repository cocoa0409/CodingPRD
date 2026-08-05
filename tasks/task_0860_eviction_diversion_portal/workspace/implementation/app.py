"""Eviction Diversion & Housing-Court Portal API — Flask entry point."""

import os

from flask import Flask

import envelope
from errors import ApiError

import routes_parties
import routes_cases
import routes_diversion
import routes_plans
import routes_court
import routes_judicial


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err.error_id, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return envelope.error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return envelope.error_response("ERR_NOT_FOUND", "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err.error_id, err.message)
        return envelope.error_response("ERR_VALIDATION", "Unexpected error: %s" % err)

    @app.after_request
    def add_conn_close(resp):
        # Avoid werkzeug keep-alive RemoteDisconnected flakiness under
        # per-test-server isolation.
        resp.headers["Connection"] = "close"
        return resp

    routes_parties.register(app)
    routes_cases.register(app)
    routes_diversion.register(app)
    routes_plans.register(app)
    routes_court.register(app)
    routes_judicial.register(app)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
