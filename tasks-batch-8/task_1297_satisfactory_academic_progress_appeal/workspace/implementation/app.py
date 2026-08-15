"""SAP Appeals API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000), in the foreground. The in-memory store
starts empty on every boot; all state is built through the declared API.
"""

import os

from flask import Flask

import errors
from db import store
from errors import ApiError
from response import error as error_response
from routes import (
    appeals,
    audit_events,
    checkpoints,
    clock,
    enrollments,
    evaluations,
    notifications,
    plans,
    programs,
    students,
    terms,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize mutations through one re-entrant lock so concurrent requests
    # cannot interleave check-then-act sequences (e.g. the OCC guard).
    @app.before_request
    def _acquire_lock():
        store.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    for module in (
        programs,
        terms,
        students,
        enrollments,
        evaluations,
        appeals,
        plans,
        checkpoints,
        notifications,
        audit_events,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource does not exist", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource does not exist", 404)

    @app.errorhandler(Exception)
    def _internal(exc):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
