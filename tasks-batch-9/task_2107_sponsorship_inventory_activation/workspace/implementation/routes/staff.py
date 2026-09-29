"""Activation staffing: roster, shifts and check-in (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from db import store, new_row, touch, ordered
from errors import ApiError
from middleware import endpoint
from response import ok, created, paginate
from services.calc import MIN_REST_MINUTES
from services.serialize import staff_member_out, staff_assignment_out
from routes.bookings import get_booking_or_404
from util import (body_of, v_str, v_int, v_enum, v_dt, v_pagination, v_query_enum,
                  gap_minutes, minutes_between)

bp = Blueprint("staff", __name__)

STAFF_STATUSES = {"ACTIVE", "INACTIVE"}
ASSIGNMENT_STATUSES = {"ASSIGNED", "CHECKED_IN", "NO_SHOW", "RELEASED"}
READ_ROLES = ["PropertyAdmin", "ContractApprover", "ActivationManager", "PerformanceAuditor"]


def get_staff_member_or_404(staff_member_id):
    member = store.staff_members.get(staff_member_id)
    if member is None:
        raise ApiError("ERR_STAFF_MEMBER_NOT_FOUND", 404)
    return member


def get_assignment_or_404(assignment_id):
    assignment = store.staff_assignments.get(assignment_id)
    if assignment is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404)
    return assignment


@bp.post("/staff-members")
@endpoint(["ActivationManager"])
def create_staff_member():
    body = body_of(request)
    full_name = v_str(body, "full_name", min_len=1, max_len=120)
    hourly_rate_cents = v_int(body, "hourly_rate_cents", min_v=0)
    status = v_enum(body, "status", STAFF_STATUSES, required=False, default="ACTIVE")

    row = new_row()
    row.update({
        "full_name": full_name,
        "hourly_rate_cents": hourly_rate_cents,
        "status": status,
        "scheduled_minutes": 0,
    })
    store.staff_members[row["id"]] = row
    return created(staff_member_out(row))


@bp.post("/asset-bookings/<booking_id>/assignments")
@endpoint(["ActivationManager"])
def create_assignment(booking_id):
    booking = get_booking_or_404(booking_id)
    body = body_of(request)
    staff_member_id = v_str(body, "staff_member_id", min_len=1)
    shift_start_raw, shift_start = v_dt(body, "shift_start")
    shift_end_raw, shift_end = v_dt(body, "shift_end")
    role_label = v_str(body, "role_label", min_len=1, max_len=60)

    member = get_staff_member_or_404(staff_member_id)

    if member["status"] != "ACTIVE":
        raise ApiError("ERR_STAFF_INACTIVE", 409)

    if shift_end <= shift_start:
        raise ApiError("ERR_INVALID_WINDOW", 422)
    if shift_start < booking["_window_start_dt"] or shift_end > booking["_window_end_dt"]:
        raise ApiError("ERR_WINDOW_OUTSIDE_TERM", 409)

    # Shifts are CLOSED intervals: touching endpoints collide. Non-touching
    # shifts of the same member need MIN_REST_MINUTES of separation.
    for other in db.assignments_of_member(member["id"]):
        if other["status"] not in ("ASSIGNED", "CHECKED_IN"):
            continue
        o_start = other["_shift_start_dt"]
        o_end = other["_shift_end_dt"]
        if shift_start <= o_end and o_start <= shift_end:
            raise ApiError("ERR_STAFF_SHIFT_CONFLICT", 409)
        if shift_start > o_end:
            gap = gap_minutes(o_end, shift_start)
        else:
            gap = gap_minutes(shift_end, o_start)
        if gap < Decimal(MIN_REST_MINUTES):
            raise ApiError("ERR_STAFF_SHIFT_CONFLICT", 409)

    row = new_row()
    row.update({
        "asset_booking_id": booking["id"],
        "staff_member_id": member["id"],
        "shift_start": shift_start_raw,
        "_shift_start_dt": shift_start,
        "shift_end": shift_end_raw,
        "_shift_end_dt": shift_end,
        "role_label": role_label,
        "status": "ASSIGNED",
    })
    store.staff_assignments[row["id"]] = row

    member["scheduled_minutes"] = member["scheduled_minutes"] + minutes_between(shift_start, shift_end)
    touch(member)
    return created(staff_assignment_out(row))


@bp.get("/staff-assignments/<assignment_id>")
@endpoint(READ_ROLES)
def read_assignment(assignment_id):
    return ok(staff_assignment_out(get_assignment_or_404(assignment_id)))


@bp.get("/staff-assignments")
@endpoint(READ_ROLES)
def list_assignments():
    status = v_query_enum(request, "status", ASSIGNMENT_STATUSES)
    limit, offset = v_pagination(request)
    asset_booking_id = request.args.get("asset_booking_id")
    staff_member_id = request.args.get("staff_member_id")

    rows = list(store.staff_assignments.values())
    if asset_booking_id is not None:
        rows = [r for r in rows if r["asset_booking_id"] == asset_booking_id]
    if staff_member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == staff_member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(ordered(rows), limit, offset, staff_assignment_out)


@bp.post("/staff-assignments/<assignment_id>/check-in")
@endpoint(["ActivationManager"])
def check_in(assignment_id):
    assignment = get_assignment_or_404(assignment_id)
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409)
    booking = store.bookings.get(assignment["asset_booking_id"])
    if booking is None or booking["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if store.now() < assignment["_shift_start_dt"]:
        raise ApiError("ERR_SHIFT_NOT_STARTED", 409)

    assignment["status"] = "CHECKED_IN"
    touch(assignment)
    return ok(staff_assignment_out(assignment))
