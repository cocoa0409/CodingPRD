"""State Budget Development & Appropriation Tracking API.

Flask application factory plus the process entry point.  All state lives in the
in-memory dicts of ``db``; a fresh process therefore starts with an empty store,
which is exactly what the per-test-server isolation mode of the harness expects.
"""

import os
import sys

try:
    from flask import Flask, request
except ModuleNotFoundError:  # first-boot dependency bootstrap, then re-exec
    # The dependency check lives here rather than in start.sh: probing with
    # `python3 -c "import flask"` costs a full flask import (3-7s on a loaded
    # host) and start.sh is re-invoked before EVERY per-test server reboot, so
    # the probe alone doubled boot time.  On the happy path this try/except is
    # free.
    import subprocess

    _here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r",
         os.path.join(_here, "requirements.txt")],
        check=True,
    )
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

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

    @app.before_request
    def drain_request_body():
        # Transport hygiene only: a request rejected before its body is parsed
        # (401/403/404 short-circuits) would otherwise leave unread bytes in the
        # socket, and closing a socket with unread data makes Linux emit RST --
        # which the client sees as "connection reset by peer" instead of the
        # response.  Reading the body up front keeps every rejection observable.
        try:
            request.get_data(cache=True)
        except Exception:  # pragma: no cover - defensive
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED",
                "That HTTP method is not allowed on this resource.",
                405,
            )
        if exc.code == 400:
            return response.error(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return response.error(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
