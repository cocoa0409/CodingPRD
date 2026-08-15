"""Corporate Volunteer Day API — Flask entry point.

Storage is in-memory only (dicts keyed by id). The store starts EMPTY on every
boot; no entity data is seeded or hardcoded at startup.
"""
import os

from flask import Flask, jsonify

from db import db
from errors import ApiError
from response import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _serialize_requests():
    """Single global lock: makes request handling deterministic under concurrency."""
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(err):
    resp = jsonify(error_body(err.error_id, err.message))
    resp.status_code = err.http_status
    return resp


@app.errorhandler(404)
def _not_found(err):
    resp = jsonify(error_body("ERR_NOT_FOUND", "resource not found"))
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def _method_not_allowed(err):
    resp = jsonify(error_body("ERR_NOT_FOUND", "method not allowed"))
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def _internal(err):
    if isinstance(err, ApiError):
        return _api_error(err)
    resp = jsonify(error_body("ERR_INTERNAL", str(err)))
    resp.status_code = 500
    return resp


# --- route registration ---
from routes.partners import bp as partners_bp
from routes.projects import bp as projects_bp
from routes.events import bp as events_bp
from routes.volunteers import bp as volunteers_bp
from routes.registrations import bp as registrations_bp
from routes.procurement import bp as procurement_bp
from routes.transport import bp as transport_bp
from routes.meals import bp as meals_bp
from routes.supervision import bp as supervision_bp
from routes.sponsorships import bp as sponsorships_bp
from routes.impact import bp as impact_bp
from routes.surveys import bp as surveys_bp
from routes.clock import bp as clock_bp

for blueprint in (
    partners_bp,
    projects_bp,
    events_bp,
    volunteers_bp,
    registrations_bp,
    procurement_bp,
    transport_bp,
    meals_bp,
    supervision_bp,
    sponsorships_bp,
    impact_bp,
    surveys_bp,
    clock_bp,
):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
