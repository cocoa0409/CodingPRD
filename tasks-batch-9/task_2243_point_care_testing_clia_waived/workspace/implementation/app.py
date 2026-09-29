"""Point-of-Care Testing Oversight API — entry point.

The in-memory store starts empty on every boot; nothing is seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_RESOURCE_NOT_FOUND", "Unknown route.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_RESOURCE_NOT_FOUND", "Method not allowed for this route.", 404)
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Malformed request.", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        # Werkzeug's development server sends `Connection: close` on every
        # response, so each API call costs a fresh TCP connection. Long test
        # sweeps churn through the ephemeral-port range fast enough to collide
        # with sockets still in TIME_WAIT, which the peer answers with a RST.
        # Waitress keeps connections alive and removes that failure mode.
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=16, _quiet=True)
    except ImportError:  # pragma: no cover - fallback when waitress is absent
        app.run(
            host="0.0.0.0",
            port=port,
            threaded=True,
            use_reloader=False,
        )
