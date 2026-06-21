"""Continuing Education Credits API — Flask entry point.

In-memory only. The store starts EMPTY on every boot — nothing is seeded. Every
entity any test needs is created through the declared API surface.
"""

import os
import socket
import time

from flask import Flask

from errors import ApiError
from response import error as error_response

# Blueprints (one per resource group).
from routes.license_boards import bp as license_boards_bp
from routes.providers import bp as providers_bp
from routes.courses import bp as courses_bp
from routes.licensees import bp as licensees_bp
from routes.renewal_cycles import bp as renewal_cycles_bp
from routes.completions import bp as completions_bp
from routes.certificates import bp as certificates_bp
from routes.audits import bp as audits_bp
from routes.reciprocity_grants import bp as reciprocity_grants_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(license_boards_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(licensees_bp)
    app.register_blueprint(renewal_cycles_bp)
    app.register_blueprint(completions_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(audits_bp)
    app.register_blueprint(reciprocity_grants_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route — surface as a generic not-found envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


def _bind_with_retry(host, port, attempts=40, delay=0.25):
    """Survive same-port races under per-test-server isolation: retry binding the
    listen port for a short window before giving up (a previous server may still
    be releasing the socket)."""
    last_err = None
    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.close()
            return
        except OSError as e:
            last_err = e
            s.close()
            time.sleep(delay)
    if last_err is not None:
        raise last_err


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    _bind_with_retry(host, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
