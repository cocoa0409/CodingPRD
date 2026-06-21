"""BNPL / Installment Lending API — Flask entry point.

In-memory only: all state lives in db.* module dicts and is wiped on every fresh
process. start.sh is re-invoked before every per-test server, so each test boots
a clean store. Nothing is seeded at startup.
"""
import errno
import os
import socket
import time

from flask import Flask
from werkzeug.serving import make_server

from errors import APIError
from response import error_response

from routes.merchants import bp as merchants_bp
from routes.borrowers import bp as borrowers_bp
from routes.applications import bp as applications_bp
from routes.disclosures import bp as disclosures_bp
from routes.loans import bp as loans_bp
from routes.installments import bp as installments_bp
from routes.payments import bp as payments_bp
from routes.returns import bp as returns_bp
from routes.autopay import bp as autopay_bp
from routes.settlements import bp as settlements_bp
from routes.operator import bp as operator_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(merchants_bp)
    app.register_blueprint(borrowers_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(installments_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(autopay_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(operator_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found."), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed."), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, APIError):
            return handle_api_error(exc)
        # Surface unexpected faults as a JSON envelope rather than an HTML page.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(exc)), 400

    return app


app = create_app()


def _serve():
    """Bind 0.0.0.0:$PORT with a short retry loop so a same-port bind race during
    rapid per-test restarts does not surface as 'server could not be restarted'."""
    port = int(os.environ.get("PORT", "10000"))
    deadline = time.time() + 30  # generous window; runner waits up to 60s
    last_err = None
    while time.time() < deadline:
        try:
            server = make_server("0.0.0.0", port, app, threaded=True)
            server.serve_forever()
            return
        except OSError as exc:  # pragma: no cover - race path
            if exc.errno in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                last_err = exc
                time.sleep(0.25)
                continue
            raise
    if last_err is not None:
        raise last_err


if __name__ == "__main__":
    _serve()
