"""Contract Lifecycle Management API — Flask entry point.

In-memory only. The store starts EMPTY on every boot — nothing is seeded.
"""

import os
import socket
import time

from flask import Flask, g

from errors import ApiError
from middleware import authenticate  # noqa: F401 (kept for clarity)
from response import error as error_response

# Blueprints
from routes.organizations import bp as organizations_bp
from routes.clause_templates import bp as clause_templates_bp
from routes.contract_templates import bp as contract_templates_bp
from routes.contracts import bp as contracts_bp
from routes.contract_versions import bp as contract_versions_bp
from routes.approval_workflows import bp as approval_workflows_bp
from routes.signature_requests import bp as signature_requests_bp
from routes.obligations import bp as obligations_bp
from routes.deviation_approvals import bp as deviation_approvals_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(organizations_bp)
    app.register_blueprint(clause_templates_bp)
    app.register_blueprint(contract_templates_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(contract_versions_bp)
    app.register_blueprint(approval_workflows_bp)
    app.register_blueprint(signature_requests_bp)
    app.register_blueprint(obligations_bp)
    app.register_blueprint(deviation_approvals_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route — surface as a generic resource-not-found envelope.
        return error_response("ERR_RESOURCE_NOT_FOUND", "Not found.", 404)

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
    """Survive same-port races under per-test-server isolation: retry binding
    the listen port for a short window before giving up (a previous server may
    still be releasing the socket)."""
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
