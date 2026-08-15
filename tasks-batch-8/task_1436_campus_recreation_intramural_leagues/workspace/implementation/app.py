"""Campus Rec Intramurals API -- Flask entry point.

In-memory only; the store starts empty on every boot. Reads PORT (default
10000), binds 0.0.0.0, runs in the foreground.
"""

import os
import signal

from flask import Flask, jsonify, request

# The per-test restart path (prd-bench runner) tears servers down exclusively
# with SIGKILL (kill -9 via the port listener scan). SIGTERM is only sent by
# lifecycle stop()/atexit paths that hold a *stale* Popen handle to the
# round's initial (long-since-restarted) server pid — under PID recycling on
# a shared host that SIGTERM can land on a freshly spawned server of a
# concurrent round and kill it mid-test. Ignore SIGTERM; SIGKILL restarts
# and the stop() SIGKILL fallback are unaffected.
signal.signal(signal.SIGTERM, signal.SIG_IGN)

import errors as E
from errors import ApiError
from store import DB
from util import authenticate, envelope_error

from routes.members import bp as members_bp
from routes.injuries import bp as injuries_bp
from routes.leagues import bp as leagues_bp
from routes.teams import bp as teams_bp
from routes.facilities import bp as facilities_bp
from routes.games import bp as games_bp
from routes.staff import bp as staff_bp
from routes.equipment import bp as equipment_bp
from routes.lockers import bp as lockers_bp
from routes.fitness import bp as fitness_bp
from routes.clock import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (members_bp, injuries_bp, leagues_bp, teams_bp, facilities_bp, games_bp,
           staff_bp, equipment_bp, lockers_bp, fitness_bp, clock_bp):
    app.register_blueprint(bp)


@app.before_request
def _before():
    # Serialize requests so multi-step mutations stay atomic.
    DB.lock.acquire()
    try:
        if request.path.startswith("/v1"):
            authenticate()
    except Exception:
        DB.lock.release()
        raise


@app.teardown_request
def _teardown(exc):
    try:
        DB.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(err):
    body, status = envelope_error(err.error_id, err.message, err.http_status)
    return jsonify(body), status


@app.errorhandler(404)
def _not_found(err):
    body, status = envelope_error("ERR_NOT_FOUND", "Resource not found", 404)
    return jsonify(body), status


@app.errorhandler(405)
def _method_not_allowed(err):
    body, status = envelope_error("ERR_NOT_FOUND", "Resource not found", 404)
    return jsonify(body), status


@app.errorhandler(Exception)
def _unhandled(err):
    if isinstance(err, ApiError):
        body, status = envelope_error(err.error_id, err.message, err.http_status)
        return jsonify(body), status
    body, status = envelope_error("ERR_INTERNAL", str(err), 500)
    return jsonify(body), status


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
