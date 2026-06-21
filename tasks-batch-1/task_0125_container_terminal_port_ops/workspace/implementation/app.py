"""Container Terminal & Port Operations API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over state
and nothing is seeded at startup.
"""
from __future__ import annotations

import os
import sys
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.clock import bp as clock_bp
from routes.berths import bp as berths_bp
from routes.vessels import bp as vessels_bp
from routes.berth_windows import bp as berth_windows_bp
from routes.containers import bp as containers_bp
from routes.yard_slots import bp as yard_slots_bp
from routes.gate_appointments import bp as gate_appointments_bp
from routes.customs_holds import bp as customs_holds_bp
from routes.demurrage_invoices import bp as demurrage_invoices_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(berths_bp)
    app.register_blueprint(vessels_bp)
    app.register_blueprint(berth_windows_bp)
    app.register_blueprint(containers_bp)
    app.register_blueprint(yard_slots_bp)
    app.register_blueprint(gate_appointments_bp)
    app.register_blueprint(customs_holds_bp)
    app.register_blueprint(demurrage_invoices_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 422)

    @app.errorhandler(415)
    def _unsupported_media(e):
        return error_response(ERR_INVALID_REQUEST, "Unsupported media type", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


def _serve(port: int, host: str = "0.0.0.0", attempts: int = 80, delay: float = 0.1):
    """Boot the WSGI server, retrying the *actual* bind on EADDRINUSE.

    Under per-test-server isolation the harness SIGKILLs the prior server and
    immediately relaunches this one on the same port. The old listener's socket
    can linger briefly (TIME_WAIT / kernel cleanup lag, magnified under the 8x
    concurrent stability sweep), so the fresh bind may raise EADDRINUSE for a
    few hundred ms. Retrying the real make_server() bind — rather than probing
    with a throwaway socket and then handing the port to Flask (a TOCTOU gap
    where the port can be re-grabbed between probe and real bind) — closes that
    race deterministically and starts serving the instant the port frees up.
    """
    from werkzeug.serving import make_server

    last_err = None
    for _ in range(attempts):
        try:
            server = make_server(host, port, app, threaded=True)
            break
        except OSError as exc:  # EADDRINUSE / EADDRNOTAVAIL while old listener dies
            last_err = exc
            time.sleep(delay)
    else:
        raise last_err if last_err is not None else OSError("could not bind")
    server.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _serve(port)
