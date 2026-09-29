"""Flask application entrypoint.

Every boot starts from a completely empty in-memory store (see db.py): no
seeding, no preloading, no file or /tmp persistence of any kind.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response
from routes import board, encounters, fees, findings, guidelines, health_centers
from routes import ops, patients, scope, sites, uds


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        ops.bp,
        health_centers.bp,
        guidelines.bp,
        board.bp,
        sites.bp,
        scope.bp,
        fees.bp,
        patients.bp,
        encounters.bp,
        uds.bp,
        findings.bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_lock():
        # One global lock keeps every multi-hop cascade atomic.
        db.LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release_lock(exc=None):
        if g.pop("_holds_lock", False):
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response(
                "ERR_VALIDATION", "No route matches the requested path.", 404
            )
        if error.code == 405:
            return error_response(
                "ERR_VALIDATION", "The method is not allowed for this path.", 405
            )
        if error.code == 400:
            return error_response("ERR_VALIDATION", "The request could not be parsed.", 400)
        return error_response(
            "ERR_VALIDATION", error.description or "Request failed.", error.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(error):  # pragma: no cover - defensive
        return error_response("ERR_VALIDATION", "Internal error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
