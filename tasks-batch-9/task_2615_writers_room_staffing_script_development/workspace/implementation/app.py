"""Writers Room Staffing & Script Development API.

In-memory only: every entity lives in the process dicts held by db.Store and
nothing is seeded at startup, so a fresh boot exposes an empty system whose
only pre-set value is the logical clock (2026-08-01T00:00:00Z).
"""
import os

from flask import Flask, g, jsonify

from db import db
from errors import ApiError
from response import error_response
from routes import (agreements, assignments, clearance, clock, credits, episodes,
                    ledger, milestones, rooms, seasons, seats, writers)

BLUEPRINTS = (
    agreements.bp,
    writers.bp,
    seasons.bp,
    rooms.bp,
    seats.bp,
    episodes.bp,
    assignments.bp,
    milestones.bp,
    clearance.bp,
    credits.bp,
    ledger.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._db_locked = True

    @app.teardown_request
    def _release(exc=None):
        if g.pop("_db_locked", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))

    @app.errorhandler(405)
    def _not_allowed(err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INTERNAL", str(err) or "internal error", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
