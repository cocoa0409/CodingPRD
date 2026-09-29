"""Hydroelectric Project Relicensing API — Flask application entry point.

State lives entirely in process memory (see db.py).  Nothing is seeded at
startup, so every fresh process begins with a completely empty dataset.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes_core
import routes_license
import routes_settlement
import routes_study
import routes_wqc
from errors import ERROR_STATUS, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_study.bp)
    app.register_blueprint(routes_settlement.bp)
    app.register_blueprint(routes_wqc.bp)
    app.register_blueprint(routes_license.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
            message = "The requested resource does not exist."
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "The HTTP method is not allowed on this resource."
        elif exc.code in (400, 415):
            error_id = "ERR_INVALID_REQUEST"
            message = "The request could not be parsed."
        else:
            error_id = "ERR_INTERNAL"
            message = exc.description or "Unexpected error."
        status = exc.code or ERROR_STATUS.get(error_id, 500)
        return response.error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return response.error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
