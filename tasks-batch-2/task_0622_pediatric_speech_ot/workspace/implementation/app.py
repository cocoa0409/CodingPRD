"""Entry point: Flask app, error handlers, route registration.

In-memory storage only. State is constructed fresh on every process boot
(db.py builds an empty DB at import); nothing is seeded.
"""

import os
import socket
import time

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.children import bp as children_bp
from routes.therapists import bp as therapists_bp
from routes.evaluations import bp as evaluations_bp
from routes.plans import bp as plans_bp
from routes.goals import bp as goals_bp
from routes.authorizations import bp as authorizations_bp
from routes.appointments import bp as appointments_bp
from routes.session_notes import bp as session_notes_bp
from routes.coordination_plans import bp as coordination_bp
from routes.home_programs import bp as home_programs_bp
from routes.waitlist import bp as waitlist_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        children_bp,
        therapists_bp,
        evaluations_bp,
        plans_bp,
        goals_bp,
        authorizations_bp,
        appointments_bp,
        session_notes_bp,
        coordination_bp,
        home_programs_bp,
        waitlist_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response("ERR_INVALID_REQUEST", 400, str(exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Under the per-test-server isolation the runner SIGKILLs the previous server
    # and immediately re-spawns this one on the SAME port. A SIGKILL can leave the
    # listening socket momentarily in TIME_WAIT/cleanup, so an immediate bind may
    # fail with "address already in use". If we let that propagate the process
    # would exit and the runner's restart poll would report "could not be
    # restarted". Bind with SO_REUSEADDR and retry briefly so a transient
    # collision never turns into a boot failure.
    deadline = time.monotonic() + 12.0
    while True:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("0.0.0.0", port))
            probe.close()
            break
        except OSError:
            probe.close()
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
    app.run(host="0.0.0.0", port=port, threaded=True)
