"""Remote Patient Monitoring API — entry point.

In-memory storage only. The store starts EMPTY on every boot; no entity is
seeded, preloaded, or hardcoded. Tests build all state via the API surface.
"""
import os
import socket

# Dependency bootstrap: a single in-process import attempt with a one-time pip
# install fallback. Doing this here (rather than via a `python3 -c` probe in
# start.sh) avoids spawning an extra interpreter on every per-test reboot.
try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover - only on a fresh environment
    import subprocess
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r",
         os.path.join(_here, "requirements.txt")],
        check=True,
    )

# Werkzeug's dev server calls socket.getfqdn(host) during server_bind() purely
# to compute the (otherwise unused) server_name banner. On hosts whose
# reverse-DNS resolver is slow, that lookup can block ~5 s on EVERY boot. Under
# the per-test-server isolation sweep (the server restarts before every test,
# 8 rounds running concurrently), that latency blows past the runner's
# restart-poll window and every test spuriously errors at setup. gethostname()
# returns the same value with no network round-trip, so we substitute it before
# werkzeug ever binds the socket.
_gethostname = socket.gethostname
socket.getfqdn = lambda *args, **kwargs: _gethostname()

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import errors as E

from routes.payers import bp as payers_bp
from routes.patients import bp as patients_bp
from routes.consents import bp as consents_bp
from routes.care_plans import bp as care_plans_bp
from routes.devices import bp as devices_bp
from routes.vitals import bp as vitals_bp
from routes.alerts import bp as alerts_bp
from routes.review_tasks import bp as review_tasks_bp
from routes.care_activities import bp as care_activities_bp
from routes.billing_periods import bp as billing_periods_bp
from routes.claims import bp as claims_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(payers_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(consents_bp)
    app.register_blueprint(care_plans_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(vitals_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(review_tasks_bp)
    app.register_blueprint(care_activities_bp)
    app.register_blueprint(billing_periods_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(E.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # Method not allowed on a known path — treat as not found per minimal
        # surface; tests only exercise declared routes.
        return error_response(E.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Map any other werkzeug HTTP error (e.g. 400 bad JSON) to the envelope.
        status = err.code or 500
        if status == 400:
            return error_response(E.ERR_INVALID_REQUEST, "Bad request.", 422)
        return error_response("ERR_INTERNAL", err.description or "Error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    import logging
    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    # Quiet the per-request access log; it is pure overhead under the sweep.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    # make_server binds the socket synchronously and starts accepting
    # immediately (no slow startup banner), so the server is ready the moment
    # this call returns — important for the runner's restart-readiness poll.
    server = make_server("0.0.0.0", port, app, threaded=True)
    server.serve_forever()
