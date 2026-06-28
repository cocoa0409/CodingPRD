"""Attendance routes (PRD 3.3; §1.5)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import lookups
import response
from middleware import require
from services import enrollment as esvc

bp = Blueprint("attendance", __name__)

RECORD_TYPES = {"REGULAR", "MAKEUP"}


def _instructor_license_ok(instructor):
    """Priority 9: instructor active AND license_expires_on > current clock time."""
    if not instructor["active"]:
        return False
    expires = helpers.parse_dt(instructor["license_expires_on"])
    return expires > clock.now()


@bp.post("/school/attendance")
@require("Instructor")
def create_attendance():
    data = helpers.body()
    helpers.require_fields(
        data, "enrollment_id", "instructor_id", "session_date_iso",
        "scheduled_hours", "hours",
    )
    enrollment_id = helpers.require_str(data, "enrollment_id")
    instructor_id = helpers.require_str(data, "instructor_id")
    # Priority 4: body FK existence.
    lookups.fk(db.enrollments, enrollment_id)
    lookups.fk(db.instructors, instructor_id)
    session_date = helpers.require_dt(data, "session_date_iso")
    scheduled_hours = helpers.require_number(data, "scheduled_hours")
    if scheduled_hours <= 0:
        raise errors.invalid_request("scheduled_hours must be > 0")
    hours = helpers.require_number(data, "hours")
    if hours < 0:
        raise errors.invalid_request("hours must be >= 0")
    record_type = data.get("record_type", "REGULAR")
    if record_type is None:
        record_type = "REGULAR"
    if record_type not in RECORD_TYPES:
        raise errors.invalid_request("record_type must be REGULAR or MAKEUP")

    # Priority 6.1: hours must not exceed scheduled_hours.
    if hours > scheduled_hours:
        raise errors.hours_exceed_scheduled()

    row = {
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "session_date_iso": db.iso(session_date),
        "scheduled_hours": scheduled_hours,
        "hours": hours,
        "record_type": record_type,
        "status": "PENDING",
    }
    db.stamp_new(row)
    db.attendance_records[row["id"]] = row
    return response.created(row)


@bp.get("/school/attendance/<aid>")
@require("Registrar", "Instructor", "Student")
def get_attendance(aid):
    row = lookups.path(db.attendance_records, aid)
    return response.ok(row)


@bp.get("/school/attendance")
@require("Registrar", "Instructor", "Student")
def list_attendance():
    rows = list(db.attendance_records.values())
    enrollment_id = request.args.get("enrollment_id")
    instructor_id = request.args.get("instructor_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if instructor_id:
        rows = [r for r in rows if r["instructor_id"] == instructor_id]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/school/attendance/<aid>/approve")
@require("Instructor")
def approve_attendance(aid):
    row = lookups.path(db.attendance_records, aid)
    # Priority 7: state precondition.
    if row["status"] != "PENDING":
        raise errors.invalid_state()
    instructor = db.instructors[row["instructor_id"]]
    # Priority 9: instructor license.
    if not _instructor_license_ok(instructor):
        raise errors.instructor_license_invalid()
    enrollment = db.enrollments[row["enrollment_id"]]
    # Approval requires owning enrollment ACTIVE or SAP_WARNING.
    if enrollment["status"] not in ("ACTIVE", "SAP_WARNING"):
        raise errors.invalid_state("owning enrollment must be ACTIVE or SAP_WARNING")

    row["status"] = "APPROVED"
    db.touch(row)

    # Side effects on enrollment: recompute actual_hours, pace_pct, advance
    # last_attendance_iso to the later of current and this session_date, bump version.
    esvc.recompute_hours(enrollment)
    session_iso = row["session_date_iso"]
    cur = enrollment.get("last_attendance_iso")
    if cur is None or session_iso > cur:
        enrollment["last_attendance_iso"] = session_iso
    db.touch(enrollment)

    return response.ok(row)


@bp.post("/school/attendance/<aid>/void")
@require("Registrar")
def void_attendance(aid):
    row = lookups.path(db.attendance_records, aid)
    status = row["status"]
    if status not in ("APPROVED", "PENDING"):
        # Priority 7: void from any other state (e.g. VOIDED) is invalid.
        raise errors.invalid_state()
    was_approved = status == "APPROVED"
    row["status"] = "VOIDED"
    db.touch(row)
    if was_approved:
        # Recompute enrollment hours/pace from scratch (void compensation).
        enrollment = db.enrollments[row["enrollment_id"]]
        esvc.recompute_hours(enrollment)
        db.touch(enrollment)
    # Voiding a PENDING record contributes no hours; no enrollment recompute.
    return response.ok(row)
