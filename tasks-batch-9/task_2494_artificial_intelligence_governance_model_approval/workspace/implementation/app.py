"""AI Governance & Model Approval API.

Flask entry point. All state lives in process memory (see db.py) and nothing is
seeded: every record is created by clients through the declared endpoints. The
logical clock starts at 2026-08-01T00:00:00Z on every fresh boot.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import errors
import response
from errors import ApiError
from routes import (
    evaluations,
    incidents,
    model_assets,
    notices,
    ops,
    oversight,
    review_gates,
    shadows,
    use_cases,
)

_LOCK = threading.Lock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        model_assets,
        use_cases,
        review_gates,
        oversight,
        evaluations,
        notices,
        incidents,
        shadows,
        ops,
    ):
        app.register_blueprint(module.bp)

    # Requests are serialised so that read-modify-write cascades stay atomic.
    @app.before_request
    def _acquire():
        _LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(_exc=None):
        if g.pop("_holds_lock", False):
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error_response(
            errors.ERR_GOVERNANCE_RECORD_NOT_FOUND, "no such route", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error_response(
            errors.ERR_INVALID_REQUEST, "method not allowed for this route", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error_response(
                errors.ERR_INVALID_REQUEST, exc.description or "bad request", 400
            )
        return response.error_response(
            errors.ERR_INVALID_REQUEST, exc.description or "request failed", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error: %s", exc)
        return response.error_response(
            errors.ERR_INVALID_REQUEST, "internal server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
