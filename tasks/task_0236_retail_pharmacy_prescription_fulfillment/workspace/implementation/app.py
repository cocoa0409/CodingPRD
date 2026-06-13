"""Retail Pharmacy Prescription Fulfillment API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.clock import bp as clock_bp
from routes.reference import bp as reference_bp
from routes.patients import bp as patients_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.fills import bp as fills_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(reference_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(fills_bp)
    app.register_blueprint(misc_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        code = exc.code or 500
        if code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer a production WSGI server (waitress) over Flask's dev server: under
    # the per-test-server isolation the process is rebooted before every test
    # and, with 8 rounds booting concurrently, the dev server can occasionally
    # accept the TCP connection while a worker thread is still warming up and
    # return a malformed/empty response (BadStatusLine). waitress serializes the
    # accept/serve handshake cleanly, eliminating that boot-window race. Fall
    # back to the dev server if waitress is unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
