"""Ride redemptions: create (queue join under height/credit/state gates), read,
list, void (with compensating refund when boarded and still LOADING)."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_SALE_NOT_ACTIVE,
    ERR_INVALID_DAY_POSTURE,
    ERR_RIDE_NOT_OPEN,
    ERR_HEIGHT_RESTRICTION,
    ERR_INSUFFICIENT_CREDITS,
    ERR_CROSS_FAIR_REFERENCE,
    ERR_REDEMPTION_NOT_VOIDABLE,
)
from helpers import get_or_404, paginate, qparam, fair_id_of_redemption
from middleware import authenticate, scope_to_fair
from response import ok
from services.cascades import refund_boarded_credit
from validators import get_body, reject_unknown, req_str

bp = Blueprint("redemptions", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


def _next_queue_position(ride_id, day_id):
    existing = [
        r["queue_position"]
        for r in store["redemptions"].values()
        if r["ride_id"] == ride_id and r["operating_day_id"] == day_id
    ]
    return (max(existing) + 1) if existing else 1


@bp.post("/ride-redemptions")
def create_redemption():
    ctx = authenticate(["RideOperator"])
    body = get_body()
    reject_unknown(body, {"wristband_id", "ride_id"})
    wristband_id = req_str(body, "wristband_id")
    ride_id = req_str(body, "ride_id")
    ride = db.get("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"] if ride else None)
    ride = get_or_404("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"])
    sale = get_or_404("sales", wristband_id)
    if sale["status"] != "ACTIVE":
        raise_err(ERR_SALE_NOT_ACTIVE, "The wristband's sale is not ACTIVE")
    day = db.get("operating_days", sale["operating_day_id"])
    if day["posture"] != "OPEN":
        raise_err(ERR_INVALID_DAY_POSTURE, "The sale's operating day is not OPEN")
    if ride["daily_status"] != "OPEN":
        raise_err(ERR_RIDE_NOT_OPEN, "The ride is not OPEN")
    height = sale["holder_height_in"]
    if height < ride["min_rider_height_in"] or height > ride["max_rider_height_in"]:
        raise_err(ERR_HEIGHT_RESTRICTION, "Rider height is outside the ride's inclusive window")
    if not sale["is_unlimited"] and sale["credits_remaining"] < 1:
        raise_err(ERR_INSUFFICIENT_CREDITS, "The wristband holds no remaining credits")
    if day["fair_id"] != ride["fair_id"]:
        raise_err(ERR_CROSS_FAIR_REFERENCE, "The wristband and the ride belong to different fairs")
    redemption = db.register(
        "redemptions",
        {
            "wristband_id": wristband_id,
            "ride_id": ride_id,
            "operating_day_id": sale["operating_day_id"],
            "ride_cycle_id": None,
            "queue_position": _next_queue_position(ride_id, sale["operating_day_id"]),
            "status": "QUEUED",
        },
    )
    return ok(serialize(redemption), 201)


@bp.get("/ride-redemptions/<rid>")
def get_redemption(rid):
    ctx = authenticate(ALL)
    redemption = get_or_404("redemptions", rid)
    scope_to_fair(ctx, fair_id_of_redemption(redemption))
    return ok(serialize(redemption))


@bp.get("/ride-redemptions")
def list_redemptions():
    authenticate(ALL)
    return paginate(
        "redemptions",
        {
            "wristband_id": qparam("wristband_id"),
            "ride_id": qparam("ride_id"),
            "operating_day_id": qparam("operating_day_id"),
            "ride_cycle_id": qparam("ride_cycle_id"),
            "status": qparam("status"),
        },
    )


@bp.post("/ride-redemptions/<rid>/void")
def void_redemption(rid):
    ctx = authenticate(["RideOperator", "TicketClerk"])
    redemption = get_or_404("redemptions", rid)
    scope_to_fair(ctx, fair_id_of_redemption(redemption))
    body = get_body()
    reject_unknown(body, set())
    voidable = False
    if redemption["status"] == "QUEUED":
        voidable = True
    elif redemption["status"] == "REDEEMED":
        cycle = db.get("cycles", redemption["ride_cycle_id"])
        if cycle is not None and cycle["status"] == "LOADING":
            voidable = True
    if not voidable:
        raise_err(ERR_REDEMPTION_NOT_VOIDABLE, "Redemption is not voidable in its current state")
    day = db.get("operating_days", redemption["operating_day_id"])
    if day["posture"] != "OPEN":
        raise_err(ERR_INVALID_DAY_POSTURE, "Voids are same-day operations gated on the OPEN posture")
    was_redeemed = redemption["status"] == "REDEEMED"
    cycle = db.get("cycles", redemption["ride_cycle_id"]) if was_redeemed else None
    redemption["status"] = "VOIDED"
    touch(redemption)
    if was_redeemed:
        refund_boarded_credit(db.get("sales", redemption["wristband_id"]))
        cycle["rider_count"] -= 1
        touch(cycle)
    return ok(serialize(redemption))
