"""Multiemployer Plan Withdrawal Liability API.

Storage is entirely in memory (plain dicts in db.py) and nothing whatsoever is
seeded: a fresh process starts with every collection empty and the logical clock
at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_collection
import routes_core
import routes_dispute
import routes_withdrawal
from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_withdrawal.bp)
    app.register_blueprint(routes_collection.bp)
    app.register_blueprint(routes_dispute.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error("ERR_INVALID_REQUEST",
                     "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                     exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
