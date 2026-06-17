"""Visitor-pass routes (PRD §3.10). Cyclic host-review loop run by Reception,
with the host (an Employee) requesting changes / approving."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_OUTSIDE_WORKDAY,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_BOOKABLE,
    ERR_SEAT_DOUBLE_BOOKED,
)
from middleware import require_role, current_user_id
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, order_by_created, get_body,
    require_str, get_visitor_pass,
)
from services.common import stamp_new, touch, public, public_list
from services import booking

bp = Blueprint("visitor_passes", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_iso_date(v):
    if not isinstance(v, str) or len(v) != 10 or v[4] != "-" or v[7] != "-":
        return False
    y, m, d = v[:4], v[5:7], v[8:10]
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return False
    return 1 <= int(m) <= 12 and 1 <= int(d) <= 31


@bp.post("/workplace/visitor-passes")
def create_visitor_pass():
    require_role("Receptionist")
    body = get_body()

    # existence of body FKs in order: host_employee_id, seat_id
    host_id = body.get("host_employee_id")
    if host_id is None or not isinstance(host_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "host_employee_id required")
    host = db.employees.get(host_id)
    if host is None:
        raise APIError(ERR_NOT_FOUND, 404, "Host employee not found")
    seat_id = body.get("seat_id")
    if seat_id is None or not isinstance(seat_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "seat_id required")
    seat = db.seats.get(seat_id)
    if seat is None:
        raise APIError(ERR_NOT_FOUND, 404, "Seat not found")

    # well-formed body
    visitor_name = require_str(body, "visitor_name")
    booking_date = body.get("booking_date")
    if not _is_iso_date(booking_date):
        raise APIError(ERR_INVALID_REQUEST, 422, "booking_date must be YYYY-MM-DD")
    start_minute = body.get("start_minute")
    end_minute = body.get("end_minute")
    if not _is_int(start_minute) or not _is_int(end_minute):
        raise APIError(ERR_INVALID_REQUEST, 422, "start_minute/end_minute must be integers")

    floor = booking.floor_of_seat(seat)
    if floor is None:
        raise APIError(ERR_NOT_FOUND, 404, "Floor not found for seat")

    # outside workday
    if not (start_minute < end_minute):
        raise APIError(ERR_OUTSIDE_WORKDAY, 422, "start_minute must be < end_minute")
    if start_minute < floor["workday_start_minute"] or end_minute > floor["workday_end_minute"]:
        raise APIError(ERR_OUTSIDE_WORKDAY, 422, "window outside floor workday")

    # resource bookable
    if seat["status"] != "AVAILABLE":
        raise APIError(ERR_RESOURCE_NOT_BOOKABLE, 409, "Seat not AVAILABLE")

    # seat overlap
    if booking.seat_window_conflict(seat_id, booking_date, start_minute, end_minute):
        raise APIError(ERR_SEAT_DOUBLE_BOOKED, 409, "Seat double-booked")

    vp = {
        "host_employee_id": host["id"],
        "seat_id": seat_id,
        "visitor_name": visitor_name,
        "booking_date": booking_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "REQUESTED",
    }
    stamp_new(vp)
    db.visitor_passes[vp["id"]] = vp
    return ok_object(public(vp), 201)


@bp.get("/workplace/visitor-passes/<vid>")
def get_visitor_pass_ep(vid):
    require_role("FacilityManager", "Receptionist", "Employee", "Analyst")
    vp = get_visitor_pass(vid)
    return ok_object(public(vp))


@bp.get("/workplace/visitor-passes")
def list_visitor_passes():
    require_role("FacilityManager", "Receptionist", "Analyst")
    limit, offset = parse_pagination()
    items = list(db.visitor_passes.values())
    f_host = request.args.get("host_employee_id")
    f_seat = request.args.get("seat_id")
    f_date = request.args.get("booking_date")
    f_status = request.args.get("status")
    if f_host is not None:
        items = [v for v in items if v["host_employee_id"] == f_host]
    if f_seat is not None:
        items = [v for v in items if v["seat_id"] == f_seat]
    if f_date is not None:
        items = [v for v in items if v["booking_date"] == f_date]
    if f_status is not None:
        items = [v for v in items if v["status"] == f_status]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.post("/workplace/visitor-passes/<vid>/request-changes")
def request_changes(vid):
    require_role("Employee")
    vp = get_visitor_pass(vid)
    # host ownership
    if vp["host_employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller is not the host")
    if vp["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Pass not REQUESTED")
    vp["status"] = "CHANGES_REQUESTED"  # frees the held window implicitly
    touch(vp)
    return ok_object(public(vp))


@bp.post("/workplace/visitor-passes/<vid>/resubmit")
def resubmit(vid):
    require_role("Receptionist")
    vp = get_visitor_pass(vid)
    if vp["status"] != "CHANGES_REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Pass not CHANGES_REQUESTED")
    body = get_body()
    new_start = vp["start_minute"]
    new_end = vp["end_minute"]
    new_date = vp["booking_date"]
    if "start_minute" in body and body["start_minute"] is not None:
        if not _is_int(body["start_minute"]):
            raise APIError(ERR_INVALID_REQUEST, 422, "start_minute must be an integer")
        new_start = body["start_minute"]
    if "end_minute" in body and body["end_minute"] is not None:
        if not _is_int(body["end_minute"]):
            raise APIError(ERR_INVALID_REQUEST, 422, "end_minute must be an integer")
        new_end = body["end_minute"]
    if "booking_date" in body and body["booking_date"] is not None:
        if not _is_iso_date(body["booking_date"]):
            raise APIError(ERR_INVALID_REQUEST, 422, "booking_date must be YYYY-MM-DD")
        new_date = body["booking_date"]

    seat = db.seats.get(vp["seat_id"])
    floor = booking.floor_of_seat(seat) if seat is not None else None
    if floor is not None:
        if not (new_start < new_end):
            raise APIError(ERR_OUTSIDE_WORKDAY, 422, "start_minute must be < end_minute")
        if new_start < floor["workday_start_minute"] or new_end > floor["workday_end_minute"]:
            raise APIError(ERR_OUTSIDE_WORKDAY, 422, "window outside floor workday")

    # re-hold: overlap re-check on the new window (exclude self)
    if booking.seat_window_conflict(vp["seat_id"], new_date, new_start, new_end,
                                    exclude_pass_id=vp["id"]):
        raise APIError(ERR_SEAT_DOUBLE_BOOKED, 409, "Seat double-booked")

    vp["start_minute"] = new_start
    vp["end_minute"] = new_end
    vp["booking_date"] = new_date
    vp["status"] = "REQUESTED"
    touch(vp)
    return ok_object(public(vp))


@bp.post("/workplace/visitor-passes/<vid>/approve")
def approve(vid):
    require_role("Employee")
    vp = get_visitor_pass(vid)
    if vp["host_employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller is not the host")
    if vp["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Pass not REQUESTED")
    # seat window free of any reservation or other visitor pass on the date
    if booking.seat_window_conflict(vp["seat_id"], vp["booking_date"],
                                    vp["start_minute"], vp["end_minute"],
                                    exclude_pass_id=vp["id"]):
        raise APIError(ERR_SEAT_DOUBLE_BOOKED, 409, "Seat double-booked")
    vp["status"] = "APPROVED"
    touch(vp)
    return ok_object(public(vp))


@bp.post("/workplace/visitor-passes/<vid>/check-in")
def visitor_check_in(vid):
    require_role("Receptionist")
    vp = get_visitor_pass(vid)
    if vp["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "Pass not APPROVED")
    vp["status"] = "CHECKED_IN"
    touch(vp)
    return ok_object(public(vp))


@bp.post("/workplace/visitor-passes/<vid>/complete")
def visitor_complete(vid):
    require_role("Receptionist")
    vp = get_visitor_pass(vid)
    if vp["status"] != "CHECKED_IN":
        raise APIError(ERR_INVALID_STATE, 409, "Pass not CHECKED_IN")
    vp["status"] = "COMPLETED"  # frees the seat window implicitly
    touch(vp)
    return ok_object(public(vp))


@bp.post("/workplace/visitor-passes/<vid>/cancel")
def visitor_cancel(vid):
    require_role("Receptionist")
    vp = get_visitor_pass(vid)
    if vp["status"] not in ("REQUESTED", "CHANGES_REQUESTED", "APPROVED"):
        raise APIError(ERR_INVALID_STATE, 409, "Pass not cancellable")
    vp["status"] = "CANCELLED"  # frees the seat window implicitly
    touch(vp)
    return ok_object(public(vp))
