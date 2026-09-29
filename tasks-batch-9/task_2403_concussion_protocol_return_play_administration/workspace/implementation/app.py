"""Concussion Protocol and Return-to-Play Administration API.

Flask application factory + entry point. All state lives in process memory
(see db.py); nothing is seeded, persisted or read from disk.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import constants as C
from errors import ApiError
from response import error_response
from routes import audits, baselines, cases, evaluations, ops, reference, reports


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(baselines.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(evaluations.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(cases.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(audits.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(reports.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(ops.bp, url_prefix=C.API_PREFIX)
    app.register_blueprint(ops.clock_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_RESOURCE_NOT_FOUND"))
        if err.code == 405:
            return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", http_status=405))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST"))
        return error_response(ApiError("ERR_INVALID_REQUEST", http_status=err.code or 500))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):  # pragma: no cover
        app.logger.exception("unhandled error: %s", err)
        return error_response(
            ApiError("ERR_INVALID_REQUEST", http_status=500, message=str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
