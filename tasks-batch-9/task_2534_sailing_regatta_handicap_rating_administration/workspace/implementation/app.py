"""Sailing Regatta & Handicap Rating Administration -- Flask entrypoint.

Every byte of state lives in the process (see store.py) and vanishes when the
process is killed. Nothing is seeded: the store boots empty on every launch and
all data is constructed through the declared endpoints.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_core
import routes_fleet
import routes_jury
import routes_racing
from errors import ApiError
from pipeline import _meta


def error_envelope(error_id, message, http_status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), http_status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_fleet.bp)
    app.register_blueprint(routes_racing.bp)
    app.register_blueprint(routes_jury.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_envelope(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_envelope("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_envelope("ERR_RESOURCE_NOT_FOUND", "No such route for that method.", 404)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_envelope("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_envelope("ERR_INVALID_REQUEST", exc.description or "Bad request", exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_envelope("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
