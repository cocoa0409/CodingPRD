"""Exam application routes (PRD 3.7; §1.5)."""
from flask import Blueprint, g, request

import db
import errors
import helpers
import lookups
import response
from middleware import require
from services import calc, enrollment as esvc

bp = Blueprint("exam_applications", __name__)

EXAM_TYPES = {"WRITTEN", "PRACTICAL"}
RESULTS = {"PASSED", "FAILED"}


def _recompute_readiness(app_row, enrollment, program):
    esvc.recompute_hours(enrollment)
    app_row["readiness_score"] = calc.exam_readiness_score(
        enrollment["actual_hours"],
        program["total_clock_hours"],
        app_row["mock_exam_avg"],
        app_row["competency_signoff_pct"],
    )


@bp.post("/school/exam-applications")
@require("Student")
def create_application():
    data = helpers.body()
    helpers.require_fields(
        data, "enrollment_id", "exam_type", "mock_exam_avg", "competency_signoff_pct",
    )
    enrollment_id = helpers.require_str(data, "enrollment_id")
    # Priority 4: body FK existence.
    enrollment = lookups.fk(db.enrollments, enrollment_id)
    exam_type = helpers.require_enum(data, "exam_type", EXAM_TYPES)
    mock_exam_avg = helpers.require_number(data, "mock_exam_avg")
    if mock_exam_avg < 0 or mock_exam_avg > 100:
        raise errors.invalid_request("mock_exam_avg must be between 0 and 100")
    competency_signoff_pct = helpers.require_number(data, "competency_signoff_pct")
    if competency_signoff_pct < 0 or competency_signoff_pct > 100:
        raise errors.invalid_request("competency_signoff_pct must be between 0 and 100")

    # Priority 8: student ownership — the acting Student must own the enrollment.
    if enrollment["student_id"] != g.user_id:
        raise errors.not_resource_owner()

    row = {
        "enrollment_id": enrollment_id,
        "exam_type": exam_type,
        "mock_exam_avg": mock_exam_avg,
        "competency_signoff_pct": competency_signoff_pct,
        "readiness_score": None,
        "status": "DRAFT",
    }
    db.stamp_new(row)
    db.exam_applications[row["id"]] = row
    return response.created(row)


@bp.get("/school/exam-applications/<eid>")
@require("Registrar", "Student")
def get_application(eid):
    row = lookups.path(db.exam_applications, eid)
    # A Student may only read applications on enrollments they own.
    if g.user_role == "Student":
        enrollment = db.enrollments[row["enrollment_id"]]
        if enrollment["student_id"] != g.user_id:
            raise errors.not_resource_owner()
    return response.ok(row)


@bp.get("/school/exam-applications")
@require("Registrar", "Student")
def list_applications():
    rows = list(db.exam_applications.values())
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if g.user_role == "Student":
        rows = [
            r for r in rows
            if db.enrollments[r["enrollment_id"]]["student_id"] == g.user_id
        ]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/school/exam-applications/<eid>/submit")
@require("Student")
def submit_application(eid):
    row = lookups.path(db.exam_applications, eid)
    enrollment = db.enrollments[row["enrollment_id"]]
    # Priority 7: state precondition (DRAFT or RETURNED_FOR_REVISION -> SUBMITTED).
    if row["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise errors.invalid_state()
    # Priority 8: student ownership.
    if enrollment["student_id"] != g.user_id:
        raise errors.not_resource_owner()
    # Owning enrollment must be ACTIVE or SAP_WARNING.
    if enrollment["status"] not in ("ACTIVE", "SAP_WARNING"):
        raise errors.invalid_state("owning enrollment must be ACTIVE or SAP_WARNING")

    program = db.programs[enrollment["program_id"]]
    row["status"] = "SUBMITTED"
    _recompute_readiness(row, enrollment, program)
    db.touch(row)
    return response.ok(row)


@bp.post("/school/exam-applications/<eid>/return")
@require("Registrar")
def return_application(eid):
    row = lookups.path(db.exam_applications, eid)
    if row["status"] != "SUBMITTED":
        raise errors.invalid_state()
    row["status"] = "RETURNED_FOR_REVISION"
    db.touch(row)
    return response.ok(row)


@bp.post("/school/exam-applications/<eid>/approve")
@require("Registrar")
def approve_application(eid):
    row = lookups.path(db.exam_applications, eid)
    if row["status"] != "SUBMITTED":
        raise errors.invalid_state()
    enrollment = db.enrollments[row["enrollment_id"]]
    program = db.programs[enrollment["program_id"]]
    esvc.recompute_hours(enrollment)
    # Priority 16: readiness gate.
    ready = (
        row["readiness_score"] is not None
        and row["readiness_score"] >= 80
        and row["competency_signoff_pct"] == 100
        and enrollment["actual_hours"] >= 0.90 * program["total_clock_hours"]
    )
    if not ready:
        raise errors.exam_not_ready()
    # Approval requires the owning enrollment to currently be ACTIVE.
    if enrollment["status"] != "ACTIVE":
        raise errors.invalid_state("owning enrollment must be ACTIVE")

    row["status"] = "APPROVED"
    db.touch(row)
    # Cross-entity bubble-up: enrollment ACTIVE -> EXAM_PENDING, bump version.
    enrollment["status"] = "EXAM_PENDING"
    db.touch(enrollment)
    return response.ok(row)


@bp.post("/school/exam-applications/<eid>/schedule")
@require("Registrar")
def schedule_application(eid):
    row = lookups.path(db.exam_applications, eid)
    if row["status"] != "APPROVED":
        raise errors.invalid_state()
    row["status"] = "SCHEDULED"
    db.touch(row)
    return response.ok(row)


@bp.post("/school/exam-applications/<eid>/record-result")
@require("Registrar")
def record_result(eid):
    row = lookups.path(db.exam_applications, eid)
    data = helpers.body()
    helpers.require_fields(data, "result")
    result = helpers.require_enum(data, "result", RESULTS)
    # Priority 7: state precondition.
    if row["status"] != "SCHEDULED":
        raise errors.invalid_state()
    enrollment = db.enrollments[row["enrollment_id"]]
    program = db.programs[enrollment["program_id"]]

    if result == "PASSED":
        # Graduation gate (priority 17): ledger_balance_cents <= 0 AND
        # actual_hours >= program.total_clock_hours.
        esvc.recompute_hours(enrollment)
        esvc.recompute_ledger(enrollment)
        if enrollment["ledger_balance_cents"] > 0:
            raise errors.outstanding_balance()
        if enrollment["actual_hours"] < program["total_clock_hours"]:
            # Hours not met blocks graduation; surface as invalid state per the
            # graduation precondition set.
            raise errors.invalid_state("actual_hours below total_clock_hours")
        row["status"] = "PASSED"
        db.touch(row)
        # Cross-entity: enrollment EXAM_PENDING -> GRADUATED, release RESERVED
        # station assignments, bump enrollment version.
        enrollment["status"] = "GRADUATED"
        for sa in db.station_assignments.values():
            if sa["enrollment_id"] == enrollment["id"] and sa["status"] == "RESERVED":
                sa["status"] = "RELEASED"
                db.touch(sa)
                station = db.stations[sa["station_id"]]
                station["status"] = "AVAILABLE"
                db.touch(station)
        db.touch(enrollment)
    else:  # FAILED
        row["status"] = "FAILED"
        db.touch(row)
        # Cross-entity: enrollment EXAM_PENDING -> ACTIVE (retake permitted).
        enrollment["status"] = "ACTIVE"
        db.touch(enrollment)

    return response.ok(row)
