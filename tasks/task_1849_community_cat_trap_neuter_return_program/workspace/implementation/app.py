"""Community Cat TNR Program API — Flask entry point.

Build contract (INSTRUCTION.md): listens on the PORT env var (default 10000),
binds 0.0.0.0, runs in the foreground. The store starts empty on every boot;
the per-test-server isolation of the test harness re-launches this process
before every test.

Request handling is serialized with a process-wide re-entrant lock so that
concurrent requests can never interleave mutations (consistency_model:
immediate).
"""

import os
import traceback

from flask import Flask

from db import LOCK
from errors import ApiError, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.appointments import bp as appointments_bp
    from routes.caretakers import bp as caretakers_bp
    from routes.cats import bp as cats_bp
    from routes.clinics import bp as clinics_bp
    from routes.clock_routes import bp as clock_bp
    from routes.colonies import bp as colonies_bp
    from routes.complaints import bp as complaints_bp
    from routes.foster import bp as foster_bp
    from routes.surgery import bp as surgery_bp
    from routes.vouchers import bp as vouchers_bp

    for bp in (clock_bp, caretakers_bp, colonies_bp, cats_bp, clinics_bp,
               appointments_bp, surgery_bp, vouchers_bp, complaints_bp,
               foster_bp):
        app.register_blueprint(bp)

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc):
        LOCK.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, f"Internal error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
