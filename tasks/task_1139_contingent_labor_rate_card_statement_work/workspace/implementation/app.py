"""Contingent Labor Rate Card & SOW Management API — Flask entry point."""

import os
import time

from flask import Flask

from envelope import error_response
from errors import ERR_NOT_FOUND, ApiError


def create_app():
    app = Flask(__name__)

    from routes import (
        assignments,
        audits,
        clock,
        conversions,
        engagements,
        invoices,
        milestones,
        offers,
        rate_cards,
        spend,
        suppliers,
        timesheets,
        workers,
    )

    for module in (
        clock,
        rate_cards,
        suppliers,
        engagements,
        offers,
        workers,
        assignments,
        timesheets,
        milestones,
        invoices,
        conversions,
        audits,
        spend,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", "The requested resource was not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "The requested resource was not found.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION", f"Unexpected server error: {e}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    # The per-test-server harness SIGKILLs the previous server and immediately
    # spawns a new one on the same port. If the kernel has not yet released
    # the listener, a single-shot bind crashes the boot and the runner's
    # 15s health poll then expires ("could not be restarted"). Retry the bind
    # inside this same process (safe: SIGTERM/SIGKILL still kill the process
    # outright; only OSError from a not-yet-free port is retried).
    port = int(os.environ.get("PORT", "10000"))
    for _attempt in range(40):  # up to ~20s, inside the runner's poll window
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break  # server exited cleanly (only via signal in practice)
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit(f"could not bind port {port}")
