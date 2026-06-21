"""ShuttleTrip endpoints and lifecycle (PRD §3.9)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_principal, require_roles
from response import success_object
from services import calculations as calc
from services.records import make_record, touch
from services.serialize import serialize_shuttle_trip
from services.validate import require_int, require_object, require_str
from timeutil import parse_iso

bp = Blueprint("shuttle_trips", __name__)


@bp.post("/shuttle-trips")
def create_shuttle_trip():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator"})

    body = require_object(request.get_json(silent=True) or {})
    lot_id = require_str(body, "lot_id")
    depart_at_raw = require_str(body, "depart_at")
    depart_at = parse_iso(depart_at_raw)
    seat_capacity = require_int(body, "seat_capacity", minimum=1)

    if lot_id not in store.lots:
        raise err("ERR_NOT_FOUND")

    rec = make_record(
        {
            "lot_id": lot_id,
            "depart_at": depart_at,
            "seat_capacity": seat_capacity,
            "seats_taken": 0,
            "status": "SCHEDULED",
        }
    )
    store.shuttle_trips[rec["id"]] = rec
    return success_object(serialize_shuttle_trip(rec), status=201)


@bp.get("/shuttle-trips/<tid>")
def get_shuttle_trip(tid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "LotOperator", "Customer"})
    rec = store.shuttle_trips.get(tid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return success_object(serialize_shuttle_trip(rec))


@bp.post("/shuttle-trips/<tid>/open-boarding")
def open_boarding(tid):
    _, role = get_principal()
    require_roles(role, {"LotOperator", "FacilityAdmin"})
    rec = store.shuttle_trips.get(tid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE")
    now = store.current_utc()
    threshold = rec["depart_at"] - _minutes(calc.BOARDING_OPEN_LEAD_MIN)
    if not (now >= threshold):
        raise err("ERR_INVALID_STATE")
    rec["status"] = "BOARDING"
    touch(rec)
    return success_object(serialize_shuttle_trip(rec))


@bp.post("/shuttle-trips/<tid>/depart")
def depart_trip(tid):
    _, role = get_principal()
    require_roles(role, {"LotOperator", "FacilityAdmin"})
    rec = store.shuttle_trips.get(tid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if rec["status"] != "BOARDING":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "DEPARTED"
    touch(rec)
    return success_object(serialize_shuttle_trip(rec))


@bp.post("/shuttle-trips/<tid>/cancel")
def cancel_trip(tid):
    _, role = get_principal()
    require_roles(role, {"LotOperator", "FacilityAdmin"})
    rec = store.shuttle_trips.get(tid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE")
    # Detach every assigned rider.
    for reservation in store.reservations.values():
        if reservation.get("shuttle_trip_id") == tid:
            reservation["shuttle_trip_id"] = None
            touch(reservation)
    rec["seats_taken"] = 0
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(serialize_shuttle_trip(rec))


def _minutes(n):
    from datetime import timedelta

    return timedelta(minutes=n)
