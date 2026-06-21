"""Engineer assignment routes (PRD §3.5)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, require_str, get_pagination, paginate,
    get_or_404, stamp_common, touch,
)
from response import success_object, success_array
from serialize import public, public_list
from services import calc
from services import booking_logic as bl

bp = Blueprint("engineer_assignments", __name__)


@bp.route("/studio/bookings/<bid>/engineer-assignments", methods=["POST"])
def assign_engineer(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    booking = get_or_404(db.bookings, bid, "booking")

    body = get_json_body()
    engineer_id = require_str(body, "engineer_id")
    engineer = get_or_404(db.engineers, engineer_id, "engineer")

    # Inactive engineer cannot be assigned (PRD §3.5 -> ERR_ENGINEER_UNAVAILABLE).
    if not engineer["active"]:
        raise err("ERR_ENGINEER_UNAVAILABLE", "engineer is not active")

    # Double-booking: engineer cannot hold ASSIGNED assignments on two bookings
    # whose windows overlap (PRD §3.5).
    my_start, my_end = bl.booking_window(booking)
    for a in db.engineer_assignments.values():
        if a["engineer_id"] != engineer_id:
            continue
        if a["status"] != "ASSIGNED":
            continue
        other_booking = db.bookings.get(a["booking_id"])
        if other_booking is None:
            continue
        if other_booking["id"] == bid:
            continue
        o_start, o_end = bl.booking_window(other_booking)
        if bl.intervals_overlap(my_start, my_end, o_start, o_end):
            raise err("ERR_ENGINEER_UNAVAILABLE", "engineer already assigned to an overlapping booking")

    # Estimate (PRD §3.5): scheduled_hours rounded up to next quarter hour.
    sched_hours = calc.scheduled_hours(my_start, my_end)
    estimate = calc.engineering_estimate_cents(sched_hours, engineer["hourly_rate_cents"])

    assignment = {
        "booking_id": bid,
        "engineer_id": engineer_id,
        "scheduled_hours": sched_hours,
        "billed_hours": sched_hours,
        "charge_cents": estimate,
        "status": "ASSIGNED",
    }
    stamp_common(assignment)
    db.engineer_assignments[assignment["id"]] = assignment

    # Creating an assignment increments the parent booking's version (PRD §3.5).
    touch(booking)
    return success_object(public(assignment), status=201)


@bp.route("/studio/bookings/<bid>/engineer-assignments", methods=["GET"])
def list_booking_assignments(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    get_or_404(db.bookings, bid, "booking")
    assignments = [a for a in db.engineer_assignments.values() if a["booking_id"] == bid]
    limit, offset = get_pagination()
    page, total = paginate(assignments, limit, offset)
    return success_array(public_list(page), limit, offset, total)


@bp.route("/studio/engineer-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    assignment = get_or_404(db.engineer_assignments, aid, "engineer assignment")
    return success_object(public(assignment))


@bp.route("/studio/engineer-assignments", methods=["GET"])
def list_assignments():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    engineer_id = request.args.get("engineer_id")
    booking_id = request.args.get("booking_id")
    assignments = list(db.engineer_assignments.values())
    if engineer_id is not None:
        assignments = [a for a in assignments if a["engineer_id"] == engineer_id]
    if booking_id is not None:
        assignments = [a for a in assignments if a["booking_id"] == booking_id]
    limit, offset = get_pagination()
    page, total = paginate(assignments, limit, offset)
    return success_array(public_list(page), limit, offset, total)


@bp.route("/studio/bookings/<bid>/engineer-assignments/<assign_id>", methods=["DELETE"])
def release_assignment(bid, assign_id):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    booking = get_or_404(db.bookings, bid, "booking")
    assignment = get_or_404(db.engineer_assignments, assign_id, "engineer assignment")
    if assignment["booking_id"] != bid:
        raise err("ERR_NOT_FOUND", "assignment does not belong to this booking")

    # State: parent booking must not be IN_SESSION or COMPLETED (PRD §3.5);
    # assignment must be ASSIGNED.
    if booking["schedule_status"] in ("IN_SESSION", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "cannot release once the session has begun or closed")
    if assignment["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "assignment is not ASSIGNED")

    assignment["status"] = "RELEASED"
    touch(assignment)
    return success_object(public(assignment))
