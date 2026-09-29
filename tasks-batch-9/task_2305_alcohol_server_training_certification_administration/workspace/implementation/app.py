"""Alcohol Server Training & Certification Administration API.

A single-process Flask application whose entire state lives in memory. The
process boots with an empty store and a logical clock pinned to
2026-08-01T00:00:00Z; nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import api_catalog
import api_credential
import api_employer
import api_training
import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(api_catalog.bp)
    app.register_blueprint(api_training.bp)
    app.register_blueprint(api_credential.bp)
    app.register_blueprint(api_employer.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(envelope.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        message = exc.description or "Request could not be routed."
        return jsonify(
            envelope.error_body("ERR_INVALID_REQUEST", message)
        ), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(
            envelope.error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)
        ), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
