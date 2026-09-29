"""The logical clock.

The service never reads the host wall clock.  Every stamp, every date
comparison and every window evaluation is driven by `core.S.clock`, which
starts at exactly 2026-08-01T00:00:00Z and only ever moves through this
endpoint.  Setting it is not a passive assignment: it is the head of
CASCADE-G, the resin-expiry cascade, whose four link counters are reported
back on the response.
"""
from flask import Blueprint

import auth
import core
import svc
from core import Checks, S, iso, touch
from errors import fail
from schema import add_schema, body_json, coerce

bp = Blueprint("clock", __name__)

SET_SPEC = {"current_utc": {"type": "ts", "required": True}}

ACTUAL_FIELDS = ("actual_oven_start_at", "actual_oven_end_at",
                 "actual_cooling_end_at")


def _latest_actual():
    """The greatest recorded actual cycle timestamp; the clock is never rolled
    backward past it."""
    latest = None
    for cycle in core.rows("molding_cycles"):
        for name in ACTUAL_FIELDS:
            stamp = cycle.get(name)
            if stamp is not None and (latest is None or stamp > latest):
                latest = stamp
    return latest


def _payload():
    body = {
        "current_utc": iso(S.clock),
        "default_utc": iso(core.DEFAULT_UTC),
    }
    body.update(S.sweep)
    return body


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, SET_SPEC)

    def not_backward():
        target = coerce(body, SET_SPEC)["current_utc"]
        latest = _latest_actual()
        if latest is not None and target < latest:
            fail("ERR_VALIDATION",
                 "The clock may not be rolled back past a recorded actual "
                 "timestamp of %s." % iso(latest))

    checks.add(24, not_backward)
    checks.run()

    # CASCADE-G link 1: the new instant is stored first, so every comparison the
    # sweep performs reads the clock the caller asked for.
    S.clock = coerce(body, SET_SPEC)["current_utc"]
    today = core.clock_date()
    expired = 0
    released = 0
    aborted = 0
    touched_cycles = []
    for lot in core.sorted_rows(core.rows("resin_lots")):
        if lot["status"] not in ("AVAILABLE", "DEPLETED", "QUARANTINED"):
            continue
        # Equality does NOT expire: a lot expiring exactly today still qualifies.
        if not lot["expires_on"] < today:
            continue
        # Link 2.
        lot["status"] = "EXPIRED"
        touch(lot)
        expired += 1
        # Link 3: RESERVED charges on the lot come back, mass returning to
        # available_kg.  CONSUMED charges are irreversible and never return.
        for charge in core.sorted_rows(core.rows("resin_charges")):
            if charge["resin_lot_id"] != lot["id"] or charge["status"] != "RESERVED":
                continue
            cycle = S.molding_cycles.get(charge["molding_cycle_id"])
            svc.release_charge(charge, "LOT_EXPIRED")
            released += 1
            if cycle is not None and cycle["id"] not in touched_cycles:
                touched_cycles.append(cycle["id"])
    # Link 4: every SCHEDULED cycle that held one of those charges aborts; a
    # cycle already past oven start keeps running on resin it has consumed.
    for cycle_id in touched_cycles:
        cycle = S.molding_cycles.get(cycle_id)
        if cycle is None:
            continue
        if cycle["status"] == "SCHEDULED":
            svc.abort_cycle(cycle, "LOT_EXPIRED", "LOT_EXPIRED")
            aborted += 1
        else:
            svc.recompute_cycle_rollups(cycle)
            touch(cycle)
    # Link 5: orders left with no qualified lot block.  Advancing the clock can
    # also disqualify a lot purely by date without expiring anything, so the
    # sweep runs on every call rather than only when a lot moved.
    blocked = svc.sweep_block_resin()
    S.sweep = {
        "expired_resin_lot_count": expired,
        "released_resin_charge_count": released,
        "aborted_molding_cycle_count": aborted,
        "blocked_production_order_count": blocked,
    }
    return core.respond(_payload())


@bp.route("/_clock/current_utc", methods=["GET"])
def read_current_utc():
    auth.authenticate(auth.READ_ALL_ROLES)
    return core.respond(_payload())
