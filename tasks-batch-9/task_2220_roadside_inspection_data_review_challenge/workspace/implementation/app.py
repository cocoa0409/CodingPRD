"""Flask application factory and entrypoint.

Every process starts with a completely empty in-memory store: no entity data is
seeded, preloaded or hardcoded anywhere.
"""

import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from db import store
from errors import ApiError
from response import error
from routes.challenges import bp as challenges_bp
from routes.plans import bp as plans_bp
from routes.reference import bp as reference_bp
from routes.reports import bp as reports_bp

METHOD_ERRORS = {
    404: ("ERR_NOT_FOUND", "The requested resource does not exist."),
    405: ("ERR_NOT_FOUND", "The requested resource does not exist."),
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(challenges_bp)
    app.register_blueprint(plans_bp)

    @app.before_request
    def _before():
        g.touched = set()
        # A rejected write must leave no partial mutation behind: mid-cascade
        # failures are rolled back to the pre-request state.
        g.rollback = None
        if request.method != "GET":
            g.rollback = store.snapshot()

    def _rollback():
        state = getattr(g, "rollback", None)
        if state is not None:
            store.restore(state)
            g.rollback = None

    @app.errorhandler(ApiError)
    def _api_error(exc):
        _rollback()
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        _rollback()
        error_id, message = METHOD_ERRORS.get(
            exc.code, ("ERR_INVALID_REQUEST", exc.description))
        status = exc.code if exc.code in (404, 405) else 400
        return error(error_id, message, status)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        _rollback()
        return error("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
