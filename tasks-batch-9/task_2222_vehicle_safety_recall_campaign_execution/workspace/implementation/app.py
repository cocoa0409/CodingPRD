"""Vehicle safety recall campaign execution API.

In-memory only: every process start begins with a completely empty store and
the logical clock pinned to 2026-08-01T00:00:00Z. Nothing is seeded.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import DEFAULT_MESSAGE, ApiError
from response import error_response
from routes.campaigns import bp as campaigns_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.filings import bp as filings_bp
from routes.parts import bp as parts_bp
from routes.population import bp as population_bp
from routes.reimbursements import bp as reimbursements_bp
from routes.waves import bp as waves_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (campaigns_bp, population_bp, waves_bp, parts_bp,
                      claims_bp, reimbursements_bp, filings_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _prepare():
        g._touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)
        message = DEFAULT_MESSAGE.get("ERR_INVALID_REQUEST", "Invalid request.")
        return error_response("ERR_INVALID_REQUEST", message, 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
