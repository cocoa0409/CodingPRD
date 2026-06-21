"""Registered Apprenticeship Tracking API — Flask entry point.

Boots a fresh, empty in-memory store on every invocation. No seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.sponsors import bp as sponsors_bp
from routes.programs import bp as programs_bp
from routes.wage_steps import bp as wage_steps_bp
from routes.milestones import bp as milestones_bp
from routes.journeyworkers import bp as journeyworkers_bp
from routes.apprentices import bp as apprentices_bp
from routes.agreements import bp as agreements_bp
from routes.ojt_entries import bp as ojt_entries_bp
from routes.rti_records import bp as rti_records_bp
from routes.milestone_attainments import bp as milestone_attainments_bp
from routes.certificates import bp as certificates_bp
from routes.eeo_reports import bp as eeo_reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        sponsors_bp,
        programs_bp,
        wage_steps_bp,
        milestones_bp,
        journeyworkers_bp,
        apprentices_bp,
        agreements_bp,
        ojt_entries_bp,
        rti_records_bp,
        milestone_attainments_bp,
        certificates_bp,
        eeo_reports_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map framework-level HTTP errors to the standard envelope.
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if e.code == 405:
            return error_response(
                "ERR_NOT_FOUND", "Method not allowed for this resource.", 405
            )
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)
        return error_response(
            "ERR_INVALID_REQUEST", e.description or "Request error.", e.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 400)

    return app


app = create_app()


def _bind_listen_socket(port):
    """Create a listening socket with aggressive reuse flags.

    Under per-test-server isolation the runner SIGKILLs the previous server and
    immediately relaunches start.sh on the SAME port. On macOS the just-freed
    listener can leave the port briefly unable to accept new connections (so a
    poller sees connection-refused) unless the new socket sets both SO_REUSEADDR
    and SO_REUSEPORT. Binding the socket ourselves with both flags, then handing
    it to Werkzeug, makes the fresh process start accepting connections as soon
    as possible — minimizing the restart-detection window.
    """
    import socket
    import time

    deadline = time.time() + 20.0
    last_err = None
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(128)
            return sock
        except OSError as e:
            last_err = e
            sock.close()
            time.sleep(0.2)
    raise last_err if last_err is not None else OSError("could not bind")


def _run(port):
    from werkzeug.serving import make_server

    sock = _bind_listen_socket(port)
    # Werkzeug accepts a pre-bound fd via the `fd` parameter.
    srv = make_server("0.0.0.0", port, app, threaded=True, fd=sock.fileno())
    srv.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _run(port)
