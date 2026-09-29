"""Employer Backup Care API — Flask application factory and entry point.

In-memory only: every collection lives in `db.Store` and is empty at boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes import employers, employees, incidents, invoices, ops, plans, providers, reservations

API_PREFIX = "/backup-care"

BLUEPRINTS = (
    ops.bp,
    employers.bp,
    plans.bp,
    employees.bp,
    providers.bp,
    reservations.bp,
    invoices.bp,
    incidents.bp,
)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", str(exc) or "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
