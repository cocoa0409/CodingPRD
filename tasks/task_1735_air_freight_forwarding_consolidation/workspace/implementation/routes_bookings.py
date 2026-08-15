"""Flight booking procurement, cutoff lifecycle, and cancellation (PRD §3.2)."""
from decimal import Decimal

from flask import Blueprint

import services as svc
from db import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import (
    ALL_ROLES,
    get_body,
    pagination_params,
    req_datetime,
    req_nonempty_str,
    req_num,
    require_roles,
)
from response import ok, ok_list

bp = Blueprint("flight_bookings", __name__)


@bp.post("/flight-bookings")
@require_roles("CapacityPlanner")
def create_booking():
    body = get_body()
    airline_code = req_nonempty_str(body, "airline_code")
    flight_number = req_nonempty_str(body, "flight_number")
    origin_code = req_nonempty_str(body, "origin_code")
    destination_code = req_nonempty_str(body, "destination_code")
    scheduled_departure_utc = req_datetime(body, "scheduled_departure_utc")
    cutoff_utc = req_datetime(body, "cutoff_utc")
    booked_weight_kg = req_num(body, "booked_weight_kg", exclusive_minimum=0)
    booked_volume_m3 = req_num(body, "booked_volume_m3", exclusive_minimum=0)
    if not cutoff_utc < scheduled_departure_utc:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "cutoff_utc must be strictly earlier than scheduled_departure_utc.",
            400,
        )
    b = svc.fresh_rec(
        airline_code=airline_code,
        flight_number=flight_number,
        origin_code=origin_code,
        destination_code=destination_code,
        scheduled_departure_utc=scheduled_departure_utc,
        cutoff_utc=cutoff_utc,
        booked_weight_kg=booked_weight_kg,
        booked_volume_m3=booked_volume_m3,
        consumed_weight_kg=Decimal(0),
        consumed_volume_m3=Decimal(0),
        utilization_pct=Decimal(0),
        status="OPEN",
    )
    store.bookings[b.id] = b
    return ok(svc.booking_json(b), 201)


@bp.get("/flight-bookings/<bid>")
@require_roles(*ALL_ROLES)
def get_booking(bid):
    b = svc.get_booking(bid)
    # Lazy cutoff auto-close against the logical clock before responding.
    svc.refresh_booking_cutoff(b)
    return ok(svc.booking_json(b), 200)


@bp.post("/flight-bookings/<bid>/cancel")
@require_roles("CapacityPlanner")
def cancel_booking(bid):
    b = svc.get_booking(bid)
    svc.refresh_booking_cutoff(b)
    if b.status not in ("OPEN", "CUTOFF_CLOSED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"Booking status is {b.status}; only OPEN or CUTOFF_CLOSED can be cancelled.",
            409,
        )
    # Atomic three-link cascade: MAWB void -> HWB detach -> capacity recompute.
    svc.cancel_booking_cascade(b)
    return ok(svc.booking_json(b), 200)


@bp.get("/flight-bookings/<bid>/master-waybills")
@require_roles(*ALL_ROLES)
def list_booking_master_waybills(bid):
    svc.get_booking(bid)
    limit, offset = pagination_params()
    items = svc.sorted_by_created(
        [m for m in store.mawbs.values() if m.booking_id == bid]
    )
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.mawb_json(m) for m in page], total, limit, offset)
