"""Ride cycles: create, read, list, load (FIFO queue boarding), dispatch,
complete (cycle-threshold suspension cascade), abort (credit refund)."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_RIDE_NOT_OPEN,
    ERR_CERTIFICATION_MISSING,
    ERR_CYCLE_IN_PROGRESS,
    ERR_CYCLE_INVALID_STATE,
    ERR_CYCLE_EMPTY,
    ERR_CROSS_FAIR_REFERENCE,
)
from helpers import (
    get_or_404,
    paginate,
    qparam,
    fair_id_of_cycle,
    has_valid_certification,
)
from middleware import authenticate, scope_to_fair, require_owner
from response import ok
from services.cascades import suspend_license_cascade, refund_boarded_credit
from validators import get_body, reject_unknown, req_str

bp = Blueprint("cycles", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


def _next_sequence(ride_id, day_id):
    existing = [
        c["sequence_number"]
        for c in store["cycles"].values()
        if c["ride_id"] == ride_id and c["operating_day_id"] == day_id
    ]
    return (max(existing) + 1) if existing else 1


@bp.post("/ride-cycles")
def create_cycle():
    ctx = authenticate(["RideOperator"])
    body = get_body()
    reject_unknown(body, {"ride_id", "operating_day_id"})
    ride_id = req_str(body, "ride_id")
    day_id = req_str(body, "operating_day_id")
    ride = db.get("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"] if ride else None)
    ride = get_or_404("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"])
    day = get_or_404("operating_days", day_id)
    if ride["daily_status"] != "OPEN":
        raise_err(ERR_RIDE_NOT_OPEN, "Cycles can only open while the ride is OPEN")
    if not has_valid_certification(ctx["user_id"], ride["ride_class"]):
        raise_err(ERR_CERTIFICATION_MISSING, "Caller lacks a valid certification for the ride's class")
    for existing in store["cycles"].values():
        if existing["ride_id"] == ride_id and existing["status"] in ("LOADING", "RUNNING"):
            raise_err(ERR_CYCLE_IN_PROGRESS, "Another cycle for this ride is already in progress")
    if day["fair_id"] != ride["fair_id"]:
        raise_err(ERR_CROSS_FAIR_REFERENCE, "The operating day belongs to a different fair than the ride")
    cycle = db.register(
        "cycles",
        {
            "ride_id": ride_id,
            "operating_day_id": day_id,
            "operator_staff_id": ctx["user_id"],
            "sequence_number": _next_sequence(ride_id, day_id),
            "status": "LOADING",
            "rider_count": 0,
        },
    )
    return ok(serialize(cycle), 201)


@bp.get("/ride-cycles/<cid>")
def get_cycle(cid):
    ctx = authenticate(ALL)
    cycle = get_or_404("cycles", cid)
    scope_to_fair(ctx, fair_id_of_cycle(cycle))
    return ok(serialize(cycle))


@bp.get("/ride-cycles")
def list_cycles():
    authenticate(ALL)
    return paginate(
        "cycles",
        {
            "ride_id": qparam("ride_id"),
            "operating_day_id": qparam("operating_day_id"),
            "operator_staff_id": qparam("operator_staff_id"),
            "status": qparam("status"),
        },
    )


@bp.post("/ride-cycles/<cid>/load")
def load_cycle(cid):
    ctx = authenticate(["RideOperator"])
    cycle = get_or_404("cycles", cid)
    scope_to_fair(ctx, fair_id_of_cycle(cycle))
    require_owner(ctx["user_id"] == cycle["operator_staff_id"])
    body = get_body()
    reject_unknown(body, set())
    if cycle["status"] != "LOADING":
        raise_err(ERR_CYCLE_INVALID_STATE, "Boarding requires the cycle to be LOADING")
    ride = db.get("rides", cycle["ride_id"])
    candidates = [
        r
        for r in store["redemptions"].values()
        if r["ride_id"] == cycle["ride_id"]
        and r["operating_day_id"] == cycle["operating_day_id"]
        and r["status"] == "QUEUED"
    ]
    candidates.sort(key=lambda r: r["queue_position"])
    for redemption in candidates:
        if cycle["rider_count"] >= ride["capacity_per_cycle"]:
            break
        band = db.get("sales", redemption["wristband_id"])
        if band["is_unlimited"]:
            pass  # unlimited instruments board with no credit movement
        elif band["credits_remaining"] >= 1:
            band["credits_remaining"] -= 1
            band["credits_redeemed"] += 1
            touch(band)
        else:
            redemption["status"] = "VOIDED"  # skipped without consuming a seat
            touch(redemption)
            continue
        redemption["status"] = "REDEEMED"
        redemption["ride_cycle_id"] = cycle["id"]
        touch(redemption)
        cycle["rider_count"] += 1
    touch(cycle)
    return ok(serialize(cycle))


@bp.post("/ride-cycles/<cid>/dispatch")
def dispatch_cycle(cid):
    ctx = authenticate(["RideOperator"])
    cycle = get_or_404("cycles", cid)
    scope_to_fair(ctx, fair_id_of_cycle(cycle))
    require_owner(ctx["user_id"] == cycle["operator_staff_id"])
    body = get_body()
    reject_unknown(body, set())
    if cycle["status"] != "LOADING":
        raise_err(ERR_CYCLE_INVALID_STATE, "Dispatch requires the cycle to be LOADING")
    if cycle["rider_count"] < 1:
        raise_err(ERR_CYCLE_EMPTY, "Cannot dispatch an empty cycle")
    ride = db.get("rides", cycle["ride_id"])
    if ride["daily_status"] != "OPEN":
        raise_err(ERR_RIDE_NOT_OPEN, "The ride is no longer OPEN")
    cycle["status"] = "RUNNING"
    touch(cycle)
    return ok(serialize(cycle))


@bp.post("/ride-cycles/<cid>/complete")
def complete_cycle(cid):
    ctx = authenticate(["RideOperator"])
    cycle = get_or_404("cycles", cid)
    scope_to_fair(ctx, fair_id_of_cycle(cycle))
    require_owner(ctx["user_id"] == cycle["operator_staff_id"])
    body = get_body()
    reject_unknown(body, set())
    if cycle["status"] != "RUNNING":
        raise_err(ERR_CYCLE_INVALID_STATE, "Completion requires the cycle to be RUNNING")
    cycle["status"] = "COMPLETED"
    touch(cycle)
    ride = db.get("rides", cycle["ride_id"])
    ride["cycles_since_inspection"] += 1
    touch(ride)
    if ride["cycles_since_inspection"] >= ride["cycle_inspection_interval"]:
        suspend_license_cascade(ride, cycle["operating_day_id"])
    return ok(serialize(cycle))


@bp.post("/ride-cycles/<cid>/abort")
def abort_cycle(cid):
    ctx = authenticate(["RideOperator"])
    cycle = get_or_404("cycles", cid)
    scope_to_fair(ctx, fair_id_of_cycle(cycle))
    require_owner(ctx["user_id"] == cycle["operator_staff_id"])
    body = get_body()
    reject_unknown(body, set())
    if cycle["status"] not in ("LOADING", "RUNNING"):
        raise_err(ERR_CYCLE_INVALID_STATE, "Abort requires the cycle to be LOADING or RUNNING")
    for redemption in store["redemptions"].values():
        if redemption["ride_cycle_id"] == cycle["id"] and redemption["status"] == "REDEEMED":
            redemption["status"] = "VOIDED"
            touch(redemption)
            refund_boarded_credit(db.get("sales", redemption["wristband_id"]))
    cycle["rider_count"] = 0
    cycle["status"] = "ABORTED"
    touch(cycle)
    return ok(serialize(cycle))
