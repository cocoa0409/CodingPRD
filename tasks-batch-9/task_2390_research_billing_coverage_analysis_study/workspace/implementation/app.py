"""Research Billing Coverage Analysis API.

Flask application factory and process entry point.  All state lives in memory
(see store.py) and starts empty on every boot.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (amendments, audit, calendars, charges, coverage, invoices,
                    ops, studies, subjects)

BLUEPRINTS = (
    studies.bp,
    coverage.bp,
    calendars.bp,
    subjects.bp,
    charges.bp,
    invoices.bp,
    audit.bp,
    amendments.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(envelope.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(envelope.error_body(
            "ERR_NOT_FOUND", "The requested resource does not exist.")), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return jsonify(envelope.error_body(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.")), 405

    @app.errorhandler(400)
    def _bad_request(_exc):
        return jsonify(envelope.error_body(
            "ERR_INVALID_REQUEST", "The request could not be parsed.")), 400

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        return jsonify(envelope.error_body(
            "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL",
            exc.description or "Request could not be handled.")), status

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        if isinstance(exc, HTTPException):
            return _http_error(exc)
        app.logger.exception("unhandled error: %s", exc)
        return jsonify(envelope.error_body(
            "ERR_INTERNAL", "An unexpected error occurred.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
