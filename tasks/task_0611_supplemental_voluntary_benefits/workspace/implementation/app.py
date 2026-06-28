"""Flask entry point for the Supplemental & Voluntary Benefits API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding, no preloading. Each start.sh
re-invocation launches a fresh process, wiping all state.
"""

import logging
import os

from flask import Flask

import errors
from response import error_response

# Silence werkzeug's per-request access log and dev-server banner. Under
# per-test-server isolation the server boots before every test and the 8-round
# sweep runs 8 of those concurrently; the access log produces a large volume of
# stderr writes that add boot/serve overhead and contend on the shared stream.
# Quieting it keeps boots inside the runner's restart window without changing any
# response. (No application behavior depends on this logging.)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

from routes.clock_route import bp as clock_bp
from routes.employers import bp as employers_bp
from routes.plan_products import bp as plan_products_bp
from routes.enrollment_periods import bp as enrollment_periods_bp
from routes.employees import bp as employees_bp
from routes.enrollments import bp as enrollments_bp
from routes.claims import bp as claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(employers_bp)
    app.register_blueprint(plan_products_bp)
    app.register_blueprint(enrollment_periods_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / unresolved path -> standard ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


def _serve(application, port):
    """Serve the WSGI app on 0.0.0.0:<port> in the foreground.

    Under per-test-server isolation the server is killed and restarted before
    every test, and the 8-round stability sweep runs 8 of those concurrently, so
    a slow or fragile bind shows up as flaky "could not be restarted" / dropped-
    connection failures. We prefer waitress: it binds immediately, has no dev
    reloader threads, and serves connections more robustly under the rapid
    connect/disconnect/kill cadence than the Werkzeug development server. If
    waitress is unavailable we fall back to the Werkzeug server so the app still
    runs self-contained.
    """
    try:
        from waitress import serve  # type: ignore
    except Exception:
        application.run(
            host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False
        )
        return
    serve(application, host="0.0.0.0", port=port, threads=8, _quiet=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _serve(app, port)
