"""Home-Staging & Real-Estate Prep API.

State lives in Python dictionaries and dies with the process: no database file,
no JSON dump, no cache directory, no pickle.  Nothing is seeded at startup.
"""
import os
import socket
import sys
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_billing
import routes_consult
import routes_core
import routes_destage
import routes_exec
import routes_pull
from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    routes_core.register(app)
    routes_consult.register(app)
    routes_pull.register(app)
    routes_exec.register(app)
    routes_destage.register(app)
    routes_billing.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return error_body("ERR_PROJECT_NOT_FOUND", "Resource not found."), 404

    @app.errorhandler(405)
    def handle_405(err):
        return error_body("ERR_UNAUTHORIZED", "Method not allowed."), 405

    @app.errorhandler(HTTPException)
    def handle_http(err):
        if err.code == 400:
            return error_body("ERR_INVALID_REQUEST", "Malformed request."), 400
        return error_body("ERR_INVALID_REQUEST", str(err)), err.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err), 500

    return app


app = create_app()


def _bind(host, port, attempts=400, delay=0.05):
    """Bounded bind-retry.  The harness kills and relaunches this process before
    every single test, so a fresh process routinely races the dying socket.  We
    retry the bind for a short bounded window instead of exiting on EADDRINUSE,
    and we keep the kill->bind window as small as possible (no fixed pre-sleep,
    which would only widen the window for an ephemeral-port steal).

    The window is bounded but generous (20s): on a saturated host the outgoing
    process can take seconds to actually die after its signal, and giving up
    early turns a slow predecessor into a hard "could not be restarted" error.
    When the port is free the very first attempt succeeds, so the ceiling costs
    nothing in the common case."""
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(2048)
            sock.setblocking(False)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except Exception:
                pass
            time.sleep(delay)
    raise SystemExit("could not bind %s:%s - %s" % (host, port, last))


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    try:
        from werkzeug.serving import make_server
        server = make_server(host, port, app, threaded=True, fd=sock.fileno())
        server.serve_forever()
    except Exception as exc:      # pragma: no cover - last-resort fallback
        sys.stderr.write("server error: %s\n" % exc)
        raise


if __name__ == "__main__":
    main()
