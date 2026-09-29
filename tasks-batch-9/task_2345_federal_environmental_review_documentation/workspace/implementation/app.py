"""Federal Environmental Review API — Flask application entry point.

Storage is entirely in-memory and starts empty on every boot; nothing is seeded,
preloaded or hardcoded.
"""

import os
import subprocess
import sys

try:
    from flask import Flask
except ModuleNotFoundError:  # pragma: no cover - first boot on a bare interpreter
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    import importlib
    import site

    importlib.invalidate_caches()
    site.main()
    from flask import Flask

from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    actions,
    alternatives,
    analysis,
    config,
    consultations,
    decisions,
    documents,
    scoping,
)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    # Preserve the declared field order of every resource in the JSON payload.
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask releases
        app.config["JSON_SORT_KEYS"] = False

    for module in (
        config,
        actions,
        scoping,
        alternatives,
        analysis,
        consultations,
        documents,
        decisions,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "malformed request", 400)
        if exc.code in (404, 405):
            return response.error("ERR_NOT_FOUND", "resource not found", 404)
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "request could not be processed", exc.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
