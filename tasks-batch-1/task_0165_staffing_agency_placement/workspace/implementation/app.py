"""Staffing Agency Placement API — entry point.

Flask app, error handlers, blueprint registration. Storage is in-memory only
(see db.py); the store starts empty on every boot. No entities are seeded.
"""

import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response

from routes.clients import bp as clients_bp
from routes.skills import bp as skills_bp
from routes.candidates import bp as candidates_bp
from routes.job_orders import bp as job_orders_bp
from routes.submissions import bp as submissions_bp
from routes.interviews import bp as interviews_bp
from routes.placements import bp as placements_bp
from routes.timesheets import bp as timesheets_bp
from routes.invoices import bp as invoices_bp
from routes.conversion_fees import bp as conversion_fees_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clients_bp, skills_bp, candidates_bp, job_orders_bp, submissions_bp,
        interviews_bp, placements_bp, timesheets_bp, invoices_bp,
        conversion_fees_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route -> generic validation-style not found is not defined;
        # return a 404 envelope with a generic error id is not in the catalog,
        # so fall back to ERR_VALIDATION semantics only for malformed routes.
        return error_response(errors.ERR_VALIDATION, "Not found.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(errors.ERR_VALIDATION, "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected errors as a 500 envelope so the client always
        # receives the standard structure.
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    import errno
    import threading
    import time

    port = int(os.environ.get("PORT", "10000"))

    # Orphan watchdog. Under per-test-server isolation the runner launches the
    # server through a shell and kills it before every test; when the launcher
    # shell is killed, this exec'd python grandchild can be reparented to init
    # (PID 1) instead of dying, lingering as an orphan that squats its port and
    # starves the shared free-port pool. Poll our parent and exit promptly once
    # orphaned. Daemon thread, no persisted state.
    def _exit_if_orphaned():
        while True:
            if os.getppid() == 1:
                os._exit(0)
            time.sleep(0.5)

    threading.Thread(target=_exit_if_orphaned, daemon=True).start()

    # Serve via waitress, a production-grade WSGI server. Under the benchmark's
    # per-test-server isolation (server restarted before every test, with 8
    # rounds running concurrently), the Flask/werkzeug dev server occasionally
    # drops a freshly accepted connection without a complete HTTP response,
    # surfacing client-side as BadStatusLine. Waitress's connection handling is
    # robust under that concurrent boot/restart load. Storage remains in-memory
    # only (db.py module dicts), so each fresh process boots with empty state.
    try:
        from waitress import serve

        def _serve():
            serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:

        def _serve():
            app.run(host="0.0.0.0", port=port, threaded=True)

    # Bind robustness. With many concurrent sweeps sharing one host, a
    # registry-assigned port can momentarily collide at bind time (another
    # runner's probe/teardown race, or a just-killed predecessor's socket not
    # yet fully released), surfacing as EADDRINUSE. Retry the bind for a bounded
    # window well under the runner's startup timeout so a transient collision
    # does not fail the round. _serve() blocks forever once the socket binds.
    deadline = time.monotonic() + 60
    while True:
        try:
            _serve()
            break
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE and time.monotonic() < deadline:
                time.sleep(0.3)
                continue
            raise
