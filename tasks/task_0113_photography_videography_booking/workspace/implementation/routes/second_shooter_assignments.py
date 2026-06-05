"""Second-shooter assignments (PRD §3.5, §2.6 OCC)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_STALE_SCHEDULE_VERSION,
    ERR_SHOOTER_DOUBLE_BOOKED,
)
from middleware import (
    require_auth, ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN,
)
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, require_int, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services import calculations as calc
from services.common import (
    stamp_create, touch, assignments_for_schedule,
    recompute_total_fee, recompute_amount_paid_and_balance,
)

bp = Blueprint("second_shooter_assignments", __name__)

TRAVEL_BUFFER_SECONDS = 60 * 60  # 60-minute buffer on each side


def _overlap_with_buffer(a_start, a_end, b_start, b_end, buffer_seconds):
    a_s = calc.parse_iso(a_start).timestamp()
    a_e = calc.parse_iso(a_end).timestamp()
    b_s = calc.parse_iso(b_start).timestamp() - buffer_seconds
    b_e = calc.parse_iso(b_end).timestamp() + buffer_seconds
    return a_s < b_e and b_s < a_e


@bp.post("/studio/shoot-schedules/<id>/second-shooter-assignments")
def create_assignment(id):
    require_auth([ROLE_STUDIO_ADMIN])
    sched = db.shoot_schedules.get(id)
    if sched is None:
        raise APIError(ERR_NOT_FOUND, 404, "Shoot schedule not found")

    body = get_body()
    photographer_id = require_str(body, "photographer_id")
    expected_version = require_int(body, "expected_shoot_schedule_version", min_value=0)

    # Body FK existence (priority 5).
    photographer = db.photographers.get(photographer_id)
    if photographer is None:
        raise APIError(ERR_INVALID_REFERENCE, 422, "Photographer does not exist")

    # OCC (priority 7): expected_shoot_schedule_version must match current version.
    if expected_version != sched["version"]:
        raise APIError(ERR_STALE_SCHEDULE_VERSION, 412,
                       "Shoot schedule version has advanced")

    # Double-booking (priority 11): same photographer ASSIGNED to an overlapping
    # window elsewhere, judged with a 60-minute travel buffer on each side.
    for other in db.second_shooter_assignments.values():
        if other["status"] != "ASSIGNED":
            continue
        if other["photographer_id"] != photographer_id:
            continue
        other_sched = db.shoot_schedules.get(other["shoot_schedule_id"])
        if other_sched is None:
            continue
        if _overlap_with_buffer(sched["start_utc"], sched["end_utc"],
                                other_sched["start_utc"], other_sched["end_utc"],
                                TRAVEL_BUFFER_SECONDS):
            raise APIError(ERR_SHOOTER_DOUBLE_BOOKED, 409,
                           "Second shooter is already booked in an overlapping window")

    # Derive billable extent from the window (round hours up).
    billable_hours = calc.second_shooter_billable_hours(sched["start_utc"], sched["end_utc"])
    assignment_fee = calc.second_shooter_fee(billable_hours, photographer["hourly_rate_cents"])

    assignment = {
        "shoot_schedule_id": sched["id"],
        "photographer_id": photographer_id,
        "billable_hours": billable_hours,
        "assignment_fee_cents": assignment_fee,
        "status": "ASSIGNED",
    }
    stamp_create(assignment)
    db.second_shooter_assignments[assignment["id"]] = assignment

    # Schedule version bumps (OCC guard target).
    touch(sched)

    # Recompute booking total and balance (ASSIGNED assignment feeds the total).
    booking = db.bookings.get(sched["booking_id"])
    if booking is not None:
        recompute_total_fee(booking)
        recompute_amount_paid_and_balance(booking)
        touch(booking)

    return ok_object(serialize(assignment), 201)


@bp.get("/studio/shoot-schedules/<id>/second-shooter-assignments")
def list_assignments_for_schedule(id):
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    sched = db.shoot_schedules.get(id)
    if sched is None:
        raise APIError(ERR_NOT_FOUND, 404, "Shoot schedule not found")
    limit, offset = parse_pagination()
    items = order_by_created_at(assignments_for_schedule(id))
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/studio/second-shooter-assignments/<id>")
def get_assignment(id):
    require_auth([ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    a = db.second_shooter_assignments.get(id)
    if a is None:
        raise APIError(ERR_NOT_FOUND, 404, "Assignment not found")
    return ok_object(serialize(a), 200)


@bp.get("/studio/second-shooter-assignments")
def list_assignments():
    require_auth([ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.second_shooter_assignments.values())
    for field in ("photographer_id", "shoot_schedule_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/second-shooter-assignments/<id>/release")
def release_assignment(id):
    require_auth([ROLE_STUDIO_ADMIN])
    a = db.second_shooter_assignments.get(id)
    if a is None:
        raise APIError(ERR_NOT_FOUND, 404, "Assignment not found")
    if a["status"] != "ASSIGNED":
        raise APIError(ERR_INVALID_STATE, 409, "Assignment is not ASSIGNED")
    a["status"] = "RELEASED"
    touch(a)

    sched = db.shoot_schedules.get(a["shoot_schedule_id"])
    booking = db.bookings.get(sched["booking_id"]) if sched else None
    if booking is not None:
        recompute_total_fee(booking)
        recompute_amount_paid_and_balance(booking)
        touch(booking)
    return ok_object(serialize(a), 200)
