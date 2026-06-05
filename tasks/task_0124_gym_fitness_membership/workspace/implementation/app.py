"""Gym & Fitness Membership API — Flask entry point.

Boots a fresh in-memory store on every process start (no seeding, no disk).
Binds 0.0.0.0:$PORT in the foreground. PORT defaults to 10000.
"""
import os
import time

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.config import bp as config_bp
from routes.members import bp as members_bp
from routes.classes import bp as classes_bp
from routes.personal_training import bp as pt_bp
from routes.billing import bp as billing_bp
from routes.guest_passes import bp as guest_passes_bp
from routes.check_ins import bp as check_ins_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(classes_bp)
    app.register_blueprint(pt_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(guest_passes_bp)
    app.register_blueprint(check_ins_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        # Map any other HTTP exception conservatively.
        code = exc.code or 500
        if code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


def main():
    port = int(os.environ.get("PORT", "10000"))
    # Bind-retry loop: under per-test-server isolation the previous server is
    # killed and a new one launched on the same port; a brief window can leave
    # the port still in TIME_WAIT/closing. On a busy host the runner-assigned
    # port can also be momentarily held by another process's ephemeral socket.
    # Retry the same port with short, frequent attempts so a transient collision
    # clears; the total budget (~60s) stays well under the runner's 120s startup
    # timeout. werkzeug.make_server sets SO_REUSEADDR, which clears TIME_WAIT.
    from werkzeug.serving import make_server
    last_err = None
    for _ in range(300):
        try:
            srv = make_server("0.0.0.0", port, app, threaded=True)
            srv.serve_forever()
            return
        except OSError as exc:
            last_err = exc
            time.sleep(0.2)
    if last_err is not None:
        raise last_err


if __name__ == "__main__":
    main()
