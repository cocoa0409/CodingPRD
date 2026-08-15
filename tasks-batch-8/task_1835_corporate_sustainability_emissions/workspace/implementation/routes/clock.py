"""Test-driving logical clock (PRD 2.5)."""
from flask import Blueprint

import calc
from envelope import ok
from errors import invalid_request
from http_util import MANAGER, get_body, parse_iso, require_roles, v_str
from store import db, now_iso, touch

bp = Blueprint("clock", __name__, url_prefix="/sustainability")


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(MANAGER)
def set_clock():
    body = get_body()
    raw = v_str(body, "to_iso8601")
    parsed = parse_iso(raw)
    if parsed is None:
        raise invalid_request("Field to_iso8601 must be a valid ISO 8601 timestamp")
    db.clock_dt = parsed

    # Due-based transitions, each firing its own side effects (PRD 2.5).
    # 1) Engagements in INVITED / NEEDS_REVISION whose due_date is strictly in
    #    the past close automatically (lighter staleness tier).
    engagements_closed = 0
    for eng in sorted(db.engagements.values(), key=lambda x: x["_seq"]):
        if eng["status"] in ("INVITED", "NEEDS_REVISION") and eng["_due_dt"] < parsed:
            eng["status"] = "CLOSED_NO_DATA"
            touch(eng)
            cycle = db.cycles.get(eng["cycle_id"])
            if cycle is not None:
                calc.mark_inventory_stale(cycle)
                touch(cycle)
            engagements_closed += 1

    # 2) PROCURED instruments age out once the clock's calendar year passes
    #    vintage_year + 3.
    instruments_expired = 0
    for inst in sorted(db.instruments.values(), key=lambda x: x["_seq"]):
        if inst["status"] == "PROCURED" and parsed.year > inst["vintage_year"] + 3:
            inst["status"] = "EXPIRED"
            touch(inst)
            instruments_expired += 1

    # 3) ACTIVE targets resolve once the clock's calendar year passes
    #    target_year.
    targets_evaluated = 0
    for t in sorted(db.targets.values(), key=lambda x: x["_seq"]):
        if t["status"] == "ACTIVE" and parsed.year > t["target_year"]:
            t["status"] = (
                "ACHIEVED" if t["trajectory_status"] == "ON_TRACK" else "MISSED"
            )
            touch(t)
            targets_evaluated += 1

    return ok(
        {
            "now_utc": now_iso(),
            "engagements_closed": engagements_closed,
            "instruments_expired": instruments_expired,
            "targets_evaluated": targets_evaluated,
        }
    )
