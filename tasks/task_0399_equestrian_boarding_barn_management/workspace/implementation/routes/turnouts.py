"""Turnout assignment routes & capacity rule (PRD §3.7 Turnouts, §3.10)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso, format_iso
from services.common import new_common, touch, require_str
from services.serialize import view
from services.lookups import get_horse, get_stall, get_turnout, require_owner_owns

bp = Blueprint("turnouts", __name__)


@bp.route("/turnout-assignments", methods=["POST"])
def create_turnout():
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    body = request.get_json(silent=True) or {}
    horse_id = require_str(body, "horse_id")
    pasture_id = require_str(body, "pasture_id")
    window_start = require_str(body, "window_start")
    window_end = require_str(body, "window_end")
    # body-FK resolution (PRD §2.5): horse_id, pasture_id (stall)
    horse = get_horse(horse_id)
    require_owner_owns(caller, horse["owner_id"])
    pasture = get_stall(pasture_id)
    # field-shape (PRD §2.7): window_end strictly after window_start; pasture kind
    try:
        ws = parse_iso(window_start)
        we = parse_iso(window_end)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "window_start/window_end must be ISO-8601 UTC")
    if not (we > ws):
        raise err("ERR_INVALID_REQUEST", "window_end must be after window_start")
    if pasture["kind"] != "PASTURE":
        raise err("ERR_INVALID_REQUEST", "pasture_id must reference a PASTURE stall")

    now = db.clock.now
    # Business-rule order per PRD §2.6: boarding-active, pasture-capacity, turnout-in-past
    if not _boarding_active_for_horse(horse["id"]):
        raise err("ERR_BOARDING_NOT_ACTIVE", "Horse boarding agreement is not ACTIVE")
    if _would_exceed_capacity(pasture, ws, we):
        raise err("ERR_PASTURE_FULL", "Concurrent turnouts would exceed pasture capacity")
    if ws < now:
        raise err("ERR_TURNOUT_IN_PAST", "window_start is before the current clock")

    turnout = new_common()
    turnout.update({
        "horse_id": horse["id"],
        "pasture_id": pasture["id"],
        "window_start": format_iso(ws),
        "window_end": format_iso(we),
        "status": "BOOKED",
    })
    db.turnouts[turnout["id"]] = turnout
    return success(view(turnout), 201)


def _boarding_active_for_horse(horse_id):
    for a in db.agreements.values():
        if a["horse_id"] == horse_id and a["status"] == "ACTIVE":
            return True
    return False


def _would_exceed_capacity(pasture, new_start, new_end):
    """Aggregate concurrent-capacity check on half-open windows (PRD §3.10).
    Reject if at any instant in [new_start, new_end) the count of BOOKED turnouts on
    this pasture whose half-open window contains the instant, INCLUDING the new one,
    would EXCEED capacity. Reaching exactly capacity is allowed.

    Candidate instants are the window_start of each existing booking that overlaps,
    plus the new booking's start: concurrency only changes at a window start within
    the new window."""
    existing = [
        t for t in db.turnouts.values()
        if t["pasture_id"] == pasture["id"] and t["status"] == "BOOKED"
    ]
    # candidate instants where concurrency could peak inside [new_start, new_end)
    instants = {new_start}
    for t in existing:
        ts = parse_iso(t["window_start"])
        if new_start <= ts < new_end:
            instants.add(ts)
    capacity = pasture["capacity"]
    for t_instant in instants:
        concurrent = 1  # the new booking
        for t in existing:
            ts = parse_iso(t["window_start"])
            te = parse_iso(t["window_end"])
            if ts <= t_instant < te:
                concurrent += 1
        if concurrent > capacity:
            return True
    return False


@bp.route("/turnout-assignments/<turnout_id>/transition", methods=["POST"])
def transition_turnout(turnout_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    turnout = get_turnout(turnout_id)
    body = request.get_json(silent=True) or {}
    target = body.get("target_status")
    if target != "CANCELLED":
        raise err("ERR_INVALID_STATE", "Unknown or illegal target_status")
    horse = db.horses.get(turnout["horse_id"])
    require_owner_owns(caller, horse["owner_id"] if horse else None)
    if turnout["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Turnout is not BOOKED")
    turnout["status"] = "CANCELLED"
    touch(turnout)
    return success(view(turnout), 200)
