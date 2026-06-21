"""Insurance Agency Management API — Flask entry point.

Registers all route blueprints, installs the standard error envelope handlers,
and launches a foreground server bound to 0.0.0.0:$PORT (default 10000).

State is purely in-memory and boots empty on every process launch (per-test-
server isolation). Nothing is seeded at startup.
"""
import os
import socket
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

# Route blueprints
from routes.carriers import bp as carriers_bp
from routes.products import bp as products_bp
from routes.producers import bp as producers_bp
from routes.licenses import bp as licenses_bp
from routes.appointments import bp as appointments_bp
from routes.accounts import bp as accounts_bp
from routes.policies import bp as policies_bp
from routes.commission_splits import bp as commission_splits_bp
from routes.trust_accounts import bp as trust_accounts_bp
from routes.commission_statements import bp as commission_statements_bp
from routes.renewal_tasks import bp as renewal_tasks_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        carriers_bp,
        products_bp,
        producers_bp,
        licenses_bp,
        appointments_bp,
        accounts_bp,
        policies_bp,
        commission_splits_bp,
        trust_accounts_bp,
        commission_statements_bp,
        renewal_tasks_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Unsupported HTTP method on a known path: surface in the standard
        # error envelope with a 405 status.
        return error_response(ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Fallback for any other werkzeug HTTP error.
        return error_response(ERR_INVALID_REQUEST, e.description or "error", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Never leak a stack trace; surface a generic 500 in the envelope.
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


def _bind_with_retry(host, port, retries=80, delay=0.25):
    """Bind the listening socket ourselves with a retry loop.

    werkzeug's make_server() swallows the bind OSError and calls sys.exit(1)
    (raising SystemExit), which would defeat a retry around make_server. By
    binding the socket here we catch the real OSError and retry, so a port still
    being released by the prior per-test-server process does not surface as a
    fatal "could not be restarted" during concurrent restarts.
    """
    last_err = None
    for _ in range(retries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.listen(128)
            s.set_inheritable(True)
            return s
        except OSError as exc:
            last_err = exc
            s.close()
            time.sleep(delay)
    raise last_err


if __name__ == "__main__":
    from werkzeug.serving import make_server

    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind_with_retry(host, port)
    # Hand the already-bound socket to werkzeug via its fd parameter so it does
    # not attempt (and fatally fail) its own bind.
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()
