"""Industrial Refrigeration (Ammonia) Service & PSM API.

Entry point: registers every route group, installs the error handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000).

Storage is purely in-memory and starts empty on every boot -- no file, no
database, no cache, and no seeded rows of any kind.  Every entity a caller
needs is created through the declared endpoints.
"""
import os
import threading

from flask import Flask

import envelope
from errors import ApiError
from store import db
from routes import (
    audits,
    charge,
    checkpoints,
    clock,
    contractors,
    drills,
    equipment,
    facilities,
    incidents,
    inspections,
    leaks,
    people,
    permits,
    psid,
    systems,
)

BLUEPRINTS = (
    clock.bp,
    facilities.bp,
    systems.bp,
    equipment.bp,
    psid.bp,
    charge.bp,
    inspections.bp,
    people.bp,
    drills.bp,
    incidents.bp,
    audits.bp,
    contractors.bp,
    permits.bp,
    leaks.bp,
    checkpoints.bp,
)

# One global lock serialises request handling: multi-step mutations (posting a
# ledger entry plus its threshold cascade, a FAIL inspection suspending permits,
# a checkpoint sweep) commit atomically even when the test harness fires
# concurrent requests at the server.
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _begin():
        _REQUEST_LOCK.acquire()
        db.begin_request()

    @app.teardown_request
    def _end(exc):
        _REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error("ERR_NOT_FOUND", "No route matches that path.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return envelope.error(
            "ERR_VALIDATION", "That method is not allowed on this path.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        status = getattr(exc, "code", None)
        if status == 404:
            return _not_found(exc)
        if status == 405:
            return _method_not_allowed(exc)
        app.logger.exception("unhandled error")
        return envelope.error(
            "ERR_VALIDATION", "The request could not be processed.", 400
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
