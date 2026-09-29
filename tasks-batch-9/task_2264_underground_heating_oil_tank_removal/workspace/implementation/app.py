"""Oil Tank Remediation API — Flask entry point.

Boots with an empty in-memory store and the logical clock at
2026-08-01T00:00:00Z, so every fresh process starts from an identical state.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import commit, db
from errors import ApiError
from response import error_response
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._lock_held = True
        g._dirty_rows = []
        g._fresh_rows = set()

    @app.after_request
    def _commit(response):
        try:
            commit()
        except Exception:  # pragma: no cover - bookkeeping must never 500
            pass
        return response

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            try:
                db.lock.release()
            except RuntimeError:  # pragma: no cover
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if error.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path.", 405)
        return error_response(
            "ERR_INVALID_REQUEST", error.description or "Request could not be processed.",
            error.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
