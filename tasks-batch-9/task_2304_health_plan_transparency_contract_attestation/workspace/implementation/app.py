"""Health Plan Transparency & Contract Attestation Compliance API.

Flask application factory and process entry point.  All state lives in the
in-memory dicts of db.py: a fresh process starts with an empty store and the
logical clock at 2026-08-01T00:00:00Z.  Nothing is seeded.
"""

import os
import subprocess
import sys

try:  # Bootstrap the only third-party dependency in-process, so that start.sh
    from flask import Flask  # needs no extra interpreter launch on the happy path.
except ImportError:  # pragma: no cover - environment bootstrap only
    _req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    _pip = [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
    if subprocess.call(_pip + ["-r", _req]) != 0:
        subprocess.check_call(_pip + ["--break-system-packages", "-r", _req])
    from flask import Flask

from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    amendments,
    attestations,
    clock_routes,
    contracts,
    disclosures,
    ledger,
    mrf,
    plan_years,
    refresh_cycles,
    remediation,
    rx,
    tools,
    vendors,
)

BLUEPRINTS = (
    plan_years.bp,
    vendors.bp,
    contracts.bp,
    amendments.bp,
    disclosures.bp,
    mrf.bp,
    refresh_cycles.bp,
    tools.bp,
    rx.bp,
    attestations.bp,
    ledger.bp,
    remediation.bp,
    clock_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed on this path.", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request refused.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unhandled server error: %s" % (exc,), 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
