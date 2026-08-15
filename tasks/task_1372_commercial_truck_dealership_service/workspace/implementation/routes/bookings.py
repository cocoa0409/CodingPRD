"""ServiceBooking endpoints (PRD §3.5)."""
from datetime import datetime, time, timedelta

from flask import Blueprint, request

from db import store, stamp_new, touch, now_dt
from errors import err_not_found, err_invalid, ApiError
from helpers import (body, req_str, opt_str, opt_int, req_dt, paginate,
                     sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import service_booking as ser
import services

bp = Blueprint("bookings", __name__)


def _get_booking(rid):
    b = store.service_bookings.get(rid)
    if b is None:
        raise err_not_found("SERVICE_BOOKING")
    return b


def _bay_within_hours(bay, start, end):
    open_dt = datetime.combine(start.date(), time(0, 0), tzinfo=start.tzinfo) \
        + timedelta(hours=bay["open_hour"])
    close_dt = datetime.combine(start.date(), time(0, 0), tzinfo=start.tzinfo) \
        + timedelta(hours=bay["close_hour"])
    return start >= open_dt and end <= close_dt


def _check_bay_overlap(bay_id, start, end):
    """Half-open [start, end): adjacency allowed."""
    for b in store.service_bookings.values():
        if b["service_bay_id"] != bay_id:
            continue
        if b["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        if b["_start_dt"] < end and start < b["_end_dt"]:
            raise ApiError("ERR_BAY_BOOKING_OVERLAP", 409,
                           "Bay booking overlaps an existing booking")


def _check_mobile_overlap(mu_id, start, end, travel):
    """Closed interval expanded by travel buffer each side: touch conflicts."""
    new_lo = start - timedelta(minutes=travel)
    new_hi = end + timedelta(minutes=travel)
    for b in store.service_bookings.values():
        if b["mobile_service_unit_id"] != mu_id:
            continue
        if b["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        ex_lo = b["_start_dt"] - timedelta(minutes=b["travel_minutes"])
        ex_hi = b["_end_dt"] + timedelta(minutes=b["travel_minutes"])
        if new_lo <= ex_hi and ex_lo <= new_hi:
            raise ApiError("ERR_MOBILE_BOOKING_OVERLAP", 409,
                           "Mobile booking overlaps after travel-buffer expansion")


@bp.post("/dealership/service-bookings")
def create_booking():
    caller(["ServiceAdvisor"])
    data = body()
    ro_id = req_str(data, "repair_order_id")
    start = req_dt(data, "start_at")
    end = req_dt(data, "end_at")
    if end <= start:
        raise err_invalid("end_at must be strictly after start_at")
    bay_id = opt_str(data, "service_bay_id")
    mu_id = opt_str(data, "mobile_service_unit_id")
    travel = opt_int(data, "travel_minutes", 0, minimum=0)

    ro = store.repair_orders.get(ro_id)
    if ro is None:
        raise err_not_found("REPAIR_ORDER")
    bay = mu = None
    if bay_id is not None:
        bay = store.service_bays.get(bay_id)
        if bay is None:
            raise err_not_found("SERVICE_BAY")
    if mu_id is not None:
        mu = store.mobile_service_units.get(mu_id)
        if mu is None:
            raise err_not_found("MOBILE_SERVICE_UNIT")

    # Resource selection (11).
    if (bay_id is None) == (mu_id is None):
        raise ApiError("ERR_SERVICE_RESOURCE_SELECTION", 422,
                       "Exactly one of service_bay_id / mobile_service_unit_id")
    if bay is not None and travel != 0:
        raise ApiError("ERR_SERVICE_RESOURCE_SELECTION", 422,
                       "travel_minutes must be 0 for bay bookings")

    # Operating hours / resource active (12).
    if bay is not None:
        if not _bay_within_hours(bay, start, end):
            raise ApiError("ERR_BAY_OUTSIDE_OPERATING_HOURS", 422,
                           "Bay booking outside operating hours")
        if bay["status"] != "ACTIVE":
            raise ApiError("ERR_RESOURCE_OUT_OF_SERVICE", 409,
                           "Service bay is OUT_OF_SERVICE")
    else:
        if mu["status"] != "ACTIVE":
            raise ApiError("ERR_RESOURCE_OUT_OF_SERVICE", 409,
                           "Mobile service unit is OUT_OF_SERVICE")

    # Overlap (16).
    if bay is not None:
        _check_bay_overlap(bay["id"], start, end)
    else:
        _check_mobile_overlap(mu["id"], start, end, travel)

    booking = {
        "repair_order_id": ro["id"],
        "service_bay_id": bay_id,
        "mobile_service_unit_id": mu_id,
        "_start_dt": start,
        "_end_dt": end,
        "travel_minutes": travel,
        "status": "BOOKED",
        "_checked_in_dt": None,
    }
    stamp_new(booking)
    store.service_bookings[booking["id"]] = booking
    if ro["work_status"] == "OPEN":
        ro["work_status"] = "SCHEDULED"
        touch(ro)
    return success(ser(booking), status=201)


@bp.get("/dealership/service-bookings")
def list_bookings():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.service_bookings.values()), [
        ("repair_order_id", request.args.get("repair_order_id")),
        ("service_bay_id", request.args.get("service_bay_id")),
        ("mobile_service_unit_id", request.args.get("mobile_service_unit_id")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(b) for b in page], meta)


@bp.get("/dealership/service-bookings/<rid>")
def get_booking(rid):
    caller(ALL_ROLES)
    return success(ser(_get_booking(rid)))


@bp.post("/dealership/service-bookings/<rid>/check-in")
def check_in(rid):
    caller(["ServiceAdvisor"])
    b = _get_booking(rid)
    if b["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_STATE", 409,
                       "Check-in requires status BOOKED")
    b["status"] = "CHECKED_IN"
    b["_checked_in_dt"] = now_dt()
    touch(b)
    return success(ser(b))


@bp.post("/dealership/service-bookings/<rid>/cancel")
def cancel_booking(rid):
    caller(["ServiceAdvisor"])
    b = _get_booking(rid)
    if b["status"] not in ("BOOKED", "CHECKED_IN"):
        raise ApiError("ERR_BOOKING_STATE", 409,
                       "Cancel requires status BOOKED or CHECKED_IN")
    b["status"] = "CANCELLED"
    touch(b)
    ro = store.repair_orders.get(b["repair_order_id"])
    if ro is not None:
        services.booking_demotion_check(ro)
    return success(ser(b))
