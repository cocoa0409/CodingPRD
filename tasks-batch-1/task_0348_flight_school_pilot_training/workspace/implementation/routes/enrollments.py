"""Enrollment routes: create, clearance, activate, suspend, complete, withdraw."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_str, get_body, get_user_context, parse_pagination,
                        require_fields, require_role)
from response import list_success, success
from services import cascade
from services.calc import NO_SHOW_SUSPEND_THRESHOLD
from services.common import fk_or_404, find_or_404

bp = Blueprint("enrollments", __name__)


@bp.post("/flight-school/enrollments")
def create_enrollment():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    require_fields(body, ["student_id", "syllabus_id"])
    student_id = as_str(body, "student_id")
    syllabus_id = as_str(body, "syllabus_id")
    # FK existence, left-to-right.
    fk_or_404(db.students, student_id)
    fk_or_404(db.syllabi, syllabus_id)

    record = new_common()
    record.update({
        "student_id": student_id,
        "syllabus_id": syllabus_id,
        "medical_status": "PENDING",
        "medical_expiry_date": None,
        "tsa_status": "PENDING",
        "logged_dual_hours": 0,
        "logged_solo_hours": 0,
        "current_stage_index": 1,
        "status": "PENDING_CLEARANCE",
    })
    db.enrollments[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/enrollments")
def list_enrollments():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    limit, offset = parse_pagination()
    items = list(db.enrollments.values())
    for field in ("student_id", "syllabus_id"):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e[field] == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(e) for e in page], limit, offset, total)


@bp.get("/flight-school/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.enrollments, enrollment_id)
    return success(public(record))


@bp.post("/flight-school/enrollments/<enrollment_id>/clearance")
def record_clearance(enrollment_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    enrollment = find_or_404(db.enrollments, enrollment_id)
    body = get_body()
    require_fields(body, ["clearance_type", "decision"])
    clearance_type = body["clearance_type"]
    decision = body["decision"]
    if clearance_type not in ("MEDICAL", "TSA"):
        raise err(errors.ERR_INVALID_REQUEST, "clearance_type must be MEDICAL or TSA.")
    if not isinstance(decision, str):
        raise err(errors.ERR_INVALID_REQUEST, "decision must be a string.")

    if clearance_type == "MEDICAL":
        # Valid medical decisions are CLEARED or EXPIRED.
        if decision not in ("CLEARED", "EXPIRED"):
            raise err(errors.ERR_INVALID_CLEARANCE_DECISION,
                      "Medical decision must be CLEARED or EXPIRED.")
        enrollment["medical_status"] = decision
        if decision == "CLEARED":
            enrollment["medical_expiry_date"] = body.get("medical_expiry_date")
        touch(enrollment)
        # Cascade: EXPIRED on an ACTIVE enrollment suspends it.
        if decision == "EXPIRED" and enrollment["status"] == "ACTIVE":
            cascade.suspend_enrollment(enrollment)
    else:  # TSA
        if decision not in ("CLEARED", "DENIED"):
            raise err(errors.ERR_INVALID_CLEARANCE_DECISION,
                      "TSA decision must be CLEARED or DENIED.")
        enrollment["tsa_status"] = decision
        touch(enrollment)

    return success(public(enrollment))


@bp.post("/flight-school/enrollments/<enrollment_id>/activate")
def activate_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    enrollment = find_or_404(db.enrollments, enrollment_id)

    # State gate.
    if enrollment["status"] not in ("PENDING_CLEARANCE", "SUSPENDED"):
        raise err(errors.ERR_ENROLLMENT_NOT_PENDING_OR_SUSPENDED,
                  "Enrollment must be PENDING_CLEARANCE or SUSPENDED to activate.")
    coming_from_suspended = enrollment["status"] == "SUSPENDED"

    # Both clearance axes.
    if enrollment["medical_status"] != "CLEARED":
        raise err(errors.ERR_MEDICAL_NOT_CLEARED, "Medical clearance not CLEARED.")
    if enrollment["tsa_status"] != "CLEARED":
        raise err(errors.ERR_TSA_NOT_CLEARED, "TSA clearance not CLEARED.")

    student = db.students[enrollment["student_id"]]
    syllabus = db.syllabi[enrollment["syllabus_id"]]

    # Re-activation from SUSPENDED has the extra no-show gate (checked before
    # the deposit minimum per PRD §3.2 narration order).
    if coming_from_suspended:
        if student["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD:
            raise err(errors.ERR_STUDENT_SUSPENDED,
                      "Student is suspended for no-show strikes.")

    if student["deposit_balance_cents"] < syllabus["min_deposit_cents"]:
        raise err(errors.ERR_DEPOSIT_BELOW_MINIMUM,
                  "Deposit balance below syllabus minimum.")

    enrollment["status"] = "ACTIVE"
    touch(enrollment)
    return success(public(enrollment))


@bp.post("/flight-school/enrollments/<enrollment_id>/suspend")
def suspend_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    enrollment = find_or_404(db.enrollments, enrollment_id)
    if enrollment["status"] != "ACTIVE":
        raise err(errors.ERR_ENROLLMENT_NOT_ACTIVE_FOR_SUSPEND,
                  "Enrollment must be ACTIVE to suspend.")
    enrollment["status"] = "SUSPENDED"
    touch(enrollment)
    cascade.cancel_open_bookings_for_enrollment(enrollment["id"])
    return success(public(enrollment))


@bp.post("/flight-school/enrollments/<enrollment_id>/complete")
def complete_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    enrollment = find_or_404(db.enrollments, enrollment_id)
    if enrollment["status"] != "ACTIVE":
        # Completion is permitted only from ACTIVE; reuse the generic state
        # error for the lifecycle here is not catalogued, so guard via the
        # specific completion preconditions narrated in §3.2. The PRD says
        # "restricted to ... permitted only from ACTIVE" — treat a non-ACTIVE
        # as not meeting the active-state requirement.
        raise err(errors.ERR_ENROLLMENT_NOT_ACTIVE,
                  "Enrollment must be ACTIVE to complete.")
    syllabus = db.syllabi[enrollment["syllabus_id"]]
    if (enrollment["logged_dual_hours"] < syllabus["required_dual_hours"]
            or enrollment["logged_solo_hours"] < syllabus["required_solo_hours"]):
        raise err(errors.ERR_HOURS_NOT_MET, "Required hours not met.")
    if enrollment["current_stage_index"] <= syllabus["stage_count"]:
        raise err(errors.ERR_STAGES_NOT_PASSED, "Not all stage checks passed.")
    has_active = any(
        b["enrollment_id"] == enrollment_id
        and b["status"] in ("REQUESTED", "CONFIRMED", "DISPATCHED")
        for b in db.bookings.values()
    )
    if has_active:
        raise err(errors.ERR_ENROLLMENT_HAS_ACTIVE_BOOKINGS,
                  "Enrollment has active bookings.")
    enrollment["status"] = "COMPLETED"
    touch(enrollment)
    return success(public(enrollment))


@bp.post("/flight-school/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    enrollment = find_or_404(db.enrollments, enrollment_id)
    # Permitted from PENDING_CLEARANCE, ACTIVE, or SUSPENDED.
    prev = enrollment["status"]
    enrollment["status"] = "WITHDRAWN"
    touch(enrollment)
    # Cascade booking cancellation only when withdrawing from PENDING_CLEARANCE
    # or ACTIVE; a withdrawal from SUSPENDED carries no booking cascade.
    if prev in ("PENDING_CLEARANCE", "ACTIVE"):
        cascade.cancel_open_bookings_for_enrollment(enrollment["id"])
    return success(public(enrollment))
