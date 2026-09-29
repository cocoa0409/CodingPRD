"""Disaster Public Assistance Grant Administration API.

Python + Flask, storage entirely in memory (see db.py). No seeding, no
persistence: every process start yields a completely empty system, which is what
the per-test-server harness relies on.

Uncatalogued error identifiers: SCAFFOLD 1.6 lists no error for three
transitions whose preconditions the PRD nevertheless pins. Those use
ERR_APPLICANT_INVALID_STATE, ERR_FACILITY_INVALID_STATE and
ERR_DEOBLIGATION_INVALID_STATE, all 409, declared in errors.py.
"""
import os
import threading

from flask import Flask, g

from db import begin_request, db
from errors import ApiError
from response import error as error_response
from routes import (
    appeals,
    applicants,
    cost_line_items,
    damage_sites,
    deobligations,
    disasters,
    drawdowns,
    facilities,
    insurance,
    progress_reports,
    projects,
    resources,
)

# One request at a time: the ledger recomputations read and write several
# collections and must not interleave.
_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for module in (disasters, applicants, facilities, damage_sites, resources,
                   insurance, projects, cost_line_items, drawdowns,
                   progress_reports, deobligations, appeals):
        app.register_blueprint(module.bp)

    @app.before_request
    def _before():
        _LOCK.acquire()
        g._holds_lock = True
        begin_request()

    @app.teardown_request
    def _teardown(exc):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "no route matches this path", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "method not allowed on this path", 405)

    @app.errorhandler(500)
    def _server_error(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "internal server error", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            return error_response("ERR_HTTP_%d" % code, str(exc), code)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "internal server error", 500)

    @app.route("/health", methods=["GET"])
    def _health():
        from db import format_instant
        from response import ok
        return ok({"status": "ok", "clock": format_instant(db.clock)})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
