"""Benefits Open Enrollment API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
(via start.sh) before every test, so there is no carry-over state. Nothing is
ever seeded at startup — every entity is constructed via the declared endpoints.
"""
from __future__ import annotations

import os
import sys
import time
import socket

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.employees import bp as employees_bp
from routes.catalog import bp as catalog_bp
from routes.dependents import bp as dependents_bp
from routes.enrollments import bp as enrollments_bp
from routes.eoi import bp as eoi_bp
from routes.life_events import bp as life_events_bp
from routes.payroll import bp as payroll_bp
from routes.forms import bp as forms_bp
from routes.clock_ctl import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(employees_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(dependents_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(eoi_bp)
    app.register_blueprint(life_events_bp)
    app.register_blueprint(payroll_bp)
    app.register_blueprint(forms_bp)
    app.register_blueprint(clock_bp)

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

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404:
                return error_response(ERR_NOT_FOUND, "Route not found", 404)
            if code == 405:
                return error_response(ERR_NOT_FOUND, "Method not allowed", 404)
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), 422 if code == 400 else code)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


def _wait_for_port_free(host: str, port: int, attempts: int = 40, delay: float = 0.25):
    """Wait for the OS to release a same-port socket left by the prior server.

    Under per-test-server isolation the runner SIGKILLs the old listener and
    immediately relaunches start.sh; the previous socket may linger for a beat.
    Probe-bind until the port accepts a bind, then hand off to werkzeug's bind.
    """
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
                return
            time.sleep(delay)


def _run_with_bind_retry(host: str, port: int, attempts: int = 50, delay: float = 0.3):
    """Start werkzeug, retrying the actual listen-socket bind on a same-port race.

    The probe in _wait_for_port_free narrows but cannot close the TOCTOU window
    between the probe's close() and werkzeug's own bind(): on a momentary collision
    werkzeug raises OSError(EADDRINUSE) and the process would die, surfacing to the
    runner as "could not be restarted". Catch that, back off, and re-attempt the
    real bind. Once app.run() is serving it never returns, so the loop body runs at
    most once on success.
    """
    last_exc = None
    for i in range(attempts):
        _wait_for_port_free(host, port)
        try:
            app.run(host=host, port=port, debug=False,
                    use_reloader=False, threaded=True)
            return
        except OSError as e:
            last_exc = e
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _run_with_bind_retry("0.0.0.0", port)
