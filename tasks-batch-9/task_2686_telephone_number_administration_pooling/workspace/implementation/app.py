"""Numbering Resource Administration platform - Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: the
process encodes the rules, never the data. Every entity is created through
the API by its caller.
"""

import os

from flask import Flask, g

from errors import ApiError
from response import error_response
from routes.allocation_requests import bp as allocation_requests_bp
from routes.blocks import bp as blocks_bp
from routes.carriers import bp as carriers_bp
from routes.clock import bp as clock_bp
from routes.filings import bp as filings_bp
from routes.npas import bp as npas_bp
from routes.ports import bp as ports_bp
from routes.rate_centers import bp as rate_centers_bp
from routes.reclamation import bp as reclamation_bp
from routes.relief import bp as relief_bp

BLUEPRINTS = (
    clock_bp,
    carriers_bp,
    npas_bp,
    rate_centers_bp,
    blocks_bp,
    allocation_requests_bp,
    filings_bp,
    reclamation_bp,
    relief_bp,
    ports_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_touch_ledger():
        # One version bump per entity per HTTP request (PRD 2.4).
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_INVALID_REQUEST", "resource not found", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        status = getattr(exc, "code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return error_response(
                "ERR_INVALID_REQUEST", str(getattr(exc, "description", exc)), status
            )
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", "internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False)
