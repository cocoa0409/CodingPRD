"""Opera & Ballet Production Management API — Flask entry point.

In-memory only (db.py module-level dicts); nothing is seeded at startup and
nothing is persisted to disk. Boots on $PORT (default 10000) bound to 0.0.0.0.
"""

import os

from flask import Flask

from db import store
from errors import ApiError
from response import error_response
from routes import (artists, build_items, call_participants, cast_assignments,
                    clock, co_production_shares, contracts, partner_companies,
                    performances, productions, rehearsal_calls, rehearsal_rooms,
                    rental_offers, roles, seat_inventories, stage_slots,
                    surtitle_tracks)

app = Flask(__name__)

for bp in (
    clock.bp,
    partner_companies.bp,
    productions.bp,
    build_items.bp,
    co_production_shares.bp,
    artists.bp,
    contracts.bp,
    roles.bp,
    cast_assignments.bp,
    rehearsal_rooms.bp,
    rehearsal_calls.bp,
    call_participants.bp,
    stage_slots.bp,
    performances.bp,
    seat_inventories.bp,
    surtitle_tracks.bp,
    rental_offers.bp,
):
    app.register_blueprint(bp)


# Serialize requests: the store is plain dicts, and per-test reboots may race
# against concurrent client traffic (e.g. OCC probes).
@app.before_request
def _acquire_store_lock():
    store.lock.acquire()


@app.teardown_request
def _release_store_lock(exc):
    store.lock.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, str(err))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
