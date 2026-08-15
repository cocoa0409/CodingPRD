"""MerchandisingSession endpoints: check-in on a trip, close, reads."""

import math
from flask import Blueprint, request

from clock import now, now_iso_ms, parse_iso
from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields,
    base_fields, paginate, err, touch, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_TRIP_NOT_FOUND, ERR_STORE_NOT_FOUND,
    ERR_SESSION_NOT_FOUND, ERR_OWNERSHIP_MISMATCH, ERR_SESSION_CONFLICT,
    ERR_SESSION_NOT_OPEN,
)
from serializers import serialize_session

bp = Blueprint("merchandising_sessions", __name__)


@bp.post("/dairy/trips/<tripId>/merchandising-sessions")
def check_in(tripId):
    user_id, _role = require_role("RouteDriver")
    trip = DB.trips.get(tripId)
    if trip is None:
        raise err(ERR_TRIP_NOT_FOUND, "TruckTrip id not found")
    if trip["driver_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller is not the trip's driver")
    body = get_json_body()
    check_unknown_fields(body, {"store_id"})
    require_fields(body, ["store_id"])
    store = DB.stores.get(body["store_id"])
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    if store["route_id"] != trip["route_id"]:
        raise err(ERR_INVALID_REQUEST, "Store must be on the trip's route")
    open_session = any(
        s["driver_id"] == user_id and s["status"] == "OPEN"
        for s in DB.merchandising_sessions.values()
    )
    if open_session:
        raise err(ERR_SESSION_CONFLICT,
                  "Driver may hold at most one OPEN merchandising session")
    s = base_fields()
    s.update({
        "trip_id": trip["id"],
        "store_id": store["id"],
        "driver_id": trip["driver_id"],
        "check_in_at": now_iso_ms(),
        "check_out_at": None,
        "minutes": None,
        "billable_minutes": None,
        "labor_charge_cents": None,
        "status": "OPEN",
    })
    DB.merchandising_sessions[s["id"]] = s
    return success_object(serialize_session(s), status=201)


@bp.post("/dairy/merchandising-sessions/<sessionId>/close")
def close_session(sessionId):
    user_id, _role = require_role("RouteDriver")
    s = DB.merchandising_sessions.get(sessionId)
    if s is None:
        raise err(ERR_SESSION_NOT_FOUND, "MerchandisingSession id not found")
    if s["driver_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller is not the session's driver")
    if s["status"] != "OPEN":
        raise err(ERR_SESSION_NOT_OPEN, "Close requires an OPEN session")
    clock = now()
    check_in = parse_iso(s["check_in_at"])
    if not (clock > check_in):
        raise err(ERR_INVALID_REQUEST,
                  "Current clock must be later than check_in_at to close")
    elapsed_seconds = (clock - check_in).total_seconds()
    minutes = int(math.ceil(elapsed_seconds / 60.0))
    if minutes <= 0:
        minutes = 1
    store = DB.stores.get(s["store_id"])
    free = store["free_merchandising_minutes"] if store else 0
    rate = store["merchandising_rate_cents_per_min"] if store else 0
    billable = max(0, minutes - free)
    s["check_out_at"] = now_iso_ms()
    s["minutes"] = minutes
    s["billable_minutes"] = billable
    s["labor_charge_cents"] = billable * rate
    s["status"] = "CLOSED"
    touch(s)
    return success_object(serialize_session(s))


@bp.get("/dairy/merchandising-sessions/<sessionId>")
def get_session(sessionId):
    require_any()
    s = DB.merchandising_sessions.get(sessionId)
    if s is None:
        raise err(ERR_SESSION_NOT_FOUND, "MerchandisingSession id not found")
    return success_object(serialize_session(s))


@bp.get("/dairy/merchandising-sessions")
def list_sessions():
    require_any()
    items = list(DB.merchandising_sessions.values())
    for param, field in (("trip_id", "trip_id"), ("store_id", "store_id"),
                         ("driver_id", "driver_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[field] == v]
    items.sort(key=lambda s: s["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_session(s) for s in page], limit, offset, total)
