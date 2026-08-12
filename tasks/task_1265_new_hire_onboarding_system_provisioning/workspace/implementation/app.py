"""New Hire Onboarding API — Flask entry point."""

import os
import threading

from flask import Flask

from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND
from util import success, error_response

app = Flask(__name__)
app.json.sort_keys = False

from routes import profiles, people, cases, tasks, clearance, provisioning, \
    orientation, checkins, training, probation, handoffs, surveys, system

for mod in (profiles, people, cases, tasks, clearance, provisioning,
            orientation, checkins, training, probation, handoffs, surveys,
            system):
    app.register_blueprint(mod.bp)

# Serialize request handling: the store is plain dicts, and the runner may
# issue concurrent requests during stability sweeps.
_LOCK = threading.RLock()


@app.before_request
def _begin():
    _LOCK.acquire()
    # Time-based transitions are evaluated on any read (and mutation) of the
    # affected entities (PRD §2.5). The sweep is idempotent: the logical
    # clock only moves via POST /api/_clock/set_current_utc, which sweeps too.
    from sweep import sweep
    sweep()


@app.teardown_request
def _end(_exc):
    _LOCK.release()


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(_):
    err = ApiError(ERR_NOT_FOUND, 404, "Resource not found")
    return error_response(err)


@app.errorhandler(405)
def _method_not_allowed(_):
    err = ApiError(ERR_VALIDATION, 405, "Method not allowed")
    return error_response(err)


@app.errorhandler(Exception)
def _unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    wrapped = ApiError(ERR_VALIDATION, 500, f"Internal error: {err}")
    return error_response(wrapped)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
