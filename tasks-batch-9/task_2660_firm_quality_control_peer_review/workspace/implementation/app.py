"""Firm Quality Control and Peer Review Management System.

A single-process Flask service. Every byte of state lives in module-level Python dicts,
so re-invoking start.sh wipes the world; nothing is ever seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import clock
import response
import routes_firm
import routes_inspection
import routes_peer
import routes_reads
import routes_sqm
import store
from errors import ApiError


def create_app():
    # PRD 4 describes the single 204 withdrawal endpoint as carrying "an empty data
    # object"; HTTP clients discard a 204 body unconditionally, so the envelope is built
    # and then dropped on the wire by Werkzeug.  A test may only assert the status code.
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    store.reset()
    clock.reset()

    app.register_blueprint(routes_reads.bp)
    app.register_blueprint(routes_firm.bp)
    app.register_blueprint(routes_sqm.bp)
    app.register_blueprint(routes_inspection.bp)
    app.register_blueprint(routes_peer.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The method is not allowed for the requested URL.", 405)
        if exc.code in (400, 415):
            return response.error_response(
                "ERR_VALIDATION_FAILED", "The request body could not be parsed.", 422)
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
