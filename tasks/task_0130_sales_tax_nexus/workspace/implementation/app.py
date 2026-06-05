"""Flask entry point for the Sales Tax Nexus API.

Boots a fresh, empty in-memory store on every process start. NO entity seeding
at startup — the test harness restarts the server before every test and builds
all preconditions through the declared API surface.
"""
import os
import socket
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_UNAUTHORIZED
from routes.config import bp as config_bp
from routes.nexus_routes import bp as nexus_bp
from routes.certificates import bp as certificates_bp
from routes.transactions import bp as transactions_bp
from routes.use_tax import bp as use_tax_bp
from routes.returns import bp as returns_bp
from routes.audit import bp as audit_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(nexus_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(use_tax_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(audit_bp)

    # ----- Error handlers -----
    @app.errorhandler(APIError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return response.error_response(ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(_e):
        # Method not allowed on a known path -> treat as not authorized route shape.
        return response.error_response(ERR_NOT_FOUND, 404, "method not allowed for this path")

    @app.errorhandler(400)
    def handle_400(e):
        msg = getattr(e, "description", None) or "bad request"
        return response.error_response(ERR_INVALID_REQUEST, 400, str(msg))

    @app.errorhandler(415)
    def handle_415(_e):
        return response.error_response(ERR_INVALID_REQUEST, 400, "unsupported media type")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Fallback: surface remaining werkzeug HTTP errors through the envelope.
        return response.error_response(ERR_INVALID_REQUEST, e.code or 400,
                                       getattr(e, "description", "error"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()


def _wait_for_port_free(host, port, attempts=40, delay=0.25):
    """During rapid per-test relaunch the previous process may still hold the
    port for a moment. Retry the bind probe so a transient EADDRINUSE does not
    crash the boot."""
    for i in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.close()
            return
        except OSError:
            s.close()
            if i == attempts - 1:
                return  # let app.run surface the error if still stuck
            time.sleep(delay)


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    _wait_for_port_free(host, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
