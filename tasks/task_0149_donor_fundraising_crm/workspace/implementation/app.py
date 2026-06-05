"""Donor & Fundraising CRM API — Flask entry point.

Registers all resource blueprints and the standard error handlers. Storage is
in-memory only (see db.py); a fresh process starts completely empty — no
seeding, no preload, no persistence.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST

from routes.households import bp as households_bp
from routes.donors import bp as donors_bp
from routes.employers import bp as employers_bp
from routes.campaigns import bp as campaigns_bp
from routes.pledges import bp as pledges_bp
from routes.gifts import bp as gifts_bp
from routes.soft_credits import bp as soft_credits_bp
from routes.match_claims import bp as match_claims_bp
from routes.planned_gifts import bp as planned_gifts_bp
from routes.acknowledgements import bp as acknowledgements_bp
from routes.segments import bp as segments_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(households_bp)
    app.register_blueprint(donors_bp)
    app.register_blueprint(employers_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(pledges_bp)
    app.register_blueprint(gifts_bp)
    app.register_blueprint(soft_credits_bp)
    app.register_blueprint(match_claims_bp)
    app.register_blueprint(planned_gifts_bp)
    app.register_blueprint(acknowledgements_bp)
    app.register_blueprint(segments_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / unresolved path id surfaced as a Werkzeug 404.
        return response.error_response(ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response(ERR_NOT_FOUND, "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return response.error_response(ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Map any other werkzeug HTTPException to the standard error envelope.
        return response.error_response(ERR_INVALID_REQUEST, err.description or "Error",
                                       err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-resort: never leak a stack trace; surface as a 400 invalid request.
        return response.error_response(ERR_INVALID_REQUEST, "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    import errno
    import socket
    import time
    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    host = "0.0.0.0"

    # Per-test-server isolation kills and relaunches this process before every
    # test, reusing the same port. The just-killed instance may not have fully
    # released the listening socket the instant we boot, so binding can
    # transiently fail with EADDRINUSE. If we let that crash the process, the
    # runner reports "could not be restarted". Werkzeug's make_server() raises
    # SystemExit (not OSError) on a busy port, so we bind the socket ourselves
    # with a bounded retry loop and hand the ready fd to make_server — the old
    # socket frees within ~1s of the kill.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    deadline = time.time() + 30.0
    while True:
        try:
            sock.bind((host, port))
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or time.time() >= deadline:
                raise
            time.sleep(0.1)
    sock.listen(128)
    httpd = make_server(host, port, app, threaded=True, fd=sock.fileno())
    httpd.serve_forever()
