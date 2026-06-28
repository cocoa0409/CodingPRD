"""Enrollment routes (PRD 3.2, 3.8; §1.5)."""
from flask import Blueprint

import db
import errors
import helpers
import lookups
import response
from middleware import require
from services import calc, enrollment as esvc

bp = Blueprint("enrollments", __name__)

PLACEMENT_VALUES = {"PLACED", "UNPLACED", "EXCLUDED"}


@bp.post("/school/enrollments")
@require("Registrar")
def create_enrollment():
    data = helpers.body()
    helpers.require_fields(data, "student_id", "program_id", "enrolled_on_iso")
    student_id = helpers.require_str(data, "student_id")
    program_id = helpers.require_str(data, "program_id")
    # Priority 4: body FK existence.
    student = lookups.fk(db.students, student_id)
    program = lookups.fk(db.programs, program_id)
    enrolled_on = helpers.require_dt(data, "enrolled_on_iso")
    scheduled_hours_to_date = helpers.opt_int(data, "scheduled_hours_to_date", 0)
    if scheduled_hours_to_date < 0:
        raise errors.invalid_request("scheduled_hours_to_date must be >= 0")

    charges = calc.total_charges(program)
    row = {
        "student_id": student_id,
        "program_id": program_id,
        "enrolled_on_iso": db.iso(enrolled_on),
        "status": "ACTIVE",
        "scheduled_hours_to_date": scheduled_hours_to_date,
        "actual_hours": 0.0,
        "pace_pct": calc.sap_pace(0.0, scheduled_hours_to_date),
        "total_charges_cents": charges,
        "total_credits_cents": 0,
        "ledger_balance_cents": charges,
        "projected_balance_cents": charges,
        "sap_warning_count": 0,
        "last_attendance_iso": None,
        "placement_status": "UNREPORTED",
    }
    db.stamp_new(row)
    db.enrollments[row["id"]] = row

    # Side effect: Student.status -> ENROLLED.
    student["status"] = "ENROLLED"
    db.touch(student)

    return response.created(esvc.serialize(row))


@bp.get("/school/enrollments/<eid>")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def get_enrollment(eid):
    row = lookups.path(db.enrollments, eid)
    return response.ok(esvc.serialize(row))


@bp.get("/school/enrollments")
@require("Registrar", "FinancialAidOfficer")
def list_enrollments():
    rows = list(db.enrollments.values())
    student_id = __import__("flask").request.args.get("student_id")
    program_id = __import__("flask").request.args.get("program_id")
    if student_id:
        rows = [r for r in rows if r["student_id"] == student_id]
    if program_id:
        rows = [r for r in rows if r["program_id"] == program_id]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing([esvc.serialize(r) for r in page], limit, offset, total)


@bp.patch("/school/enrollments/<eid>")
@require("Registrar")
def update_enrollment(eid):
    row = lookups.path(db.enrollments, eid)
    data = helpers.body()
    helpers.require_fields(data, "scheduled_hours_to_date")
    scheduled = helpers.require_int(data, "scheduled_hours_to_date")
    if scheduled < 0:
        raise errors.invalid_request("scheduled_hours_to_date must be >= 0")
    row["scheduled_hours_to_date"] = scheduled
    # Recompute pace from the new scheduled denominator (CALC sap_pace).
    esvc.recompute_pace(row)
    db.touch(row)
    return response.ok(esvc.serialize(row))


@bp.post("/school/enrollments/<eid>/evaluate-sap")
@require("Registrar")
def evaluate_sap(eid):
    row = lookups.path(db.enrollments, eid)
    # Recompute pace from current hours before comparing.
    esvc.recompute_hours(row)
    pace = row["pace_pct"]
    status = row["status"]
    if status == "ACTIVE":
        if pace < 67.00:
            row["status"] = "SAP_WARNING"
            row["sap_warning_count"] += 1
            db.touch(row)
        # pace >= 67.00 from ACTIVE: no defined transition. PRD 3.2 says an
        # evaluation requested from a state with no matching transition is
        # rejected with ERR_INVALID_STATE. ACTIVE->ACTIVE (pass) is not a
        # defined transition.
        else:
            raise errors.invalid_state()
    elif status == "SAP_WARNING":
        if pace >= 67.00:
            row["status"] = "ACTIVE"
            db.touch(row)
        else:
            raise errors.invalid_state()
    else:
        raise errors.invalid_state()
    return response.ok(esvc.serialize(row))


@bp.post("/school/enrollments/<eid>/placement")
@require("Registrar")
def record_placement(eid):
    row = lookups.path(db.enrollments, eid)
    data = helpers.body()
    helpers.require_fields(data, "placement_status")
    placement = helpers.require_enum(data, "placement_status", PLACEMENT_VALUES)
    # Priority 19: placement may only be recorded for a GRADUATED enrollment.
    if row["status"] != "GRADUATED":
        raise errors.invalid_state("placement may only be recorded for a GRADUATED enrollment")
    row["placement_status"] = placement
    db.touch(row)
    return response.ok(esvc.serialize(row))
