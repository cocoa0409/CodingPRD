"""Application endpoints: create, read, list, clearance, resubmit, approve, commit, withdraw, lifecycle."""

from flask import Blueprint, request
import db
from db import new_id, now_iso, get_clock
from middleware import get_auth, require_role, check_student_ownership
from response import success_object, success_list
from utils import require_string, require_enum, parse_dt, parse_pagination
from errors import (
    not_found, invalid_request, invalid_state, forbidden, ApiError,
    ERR_GPA_BELOW_MINIMUM, ERR_CONDUCT_HOLD, ERR_APPLICATION_DEADLINE_PASSED,
    ERR_DUPLICATE_APPLICATION, ERR_PROGRAM_FULL, ERR_TRAVEL_ADVISORY_BLOCK,
    ERR_SEGREGATION_OF_DUTIES, ERR_INSURANCE_COVERAGE_MISSING,
)
from services.program import recompute_seats, active_blocking_advisory
from services.billing import create_billing_statement
from services.cascade import withdraw_application

bp = Blueprint("applications", __name__)

ACTIVE_APP_STATUSES = {
    "SUBMITTED", "RETURNED_FOR_REVISION", "CLEARED", "APPROVED",
    "COMMITTED", "ABROAD", "RETURNED_HOME",
}
WITHDRAWABLE = {"SUBMITTED", "RETURNED_FOR_REVISION", "CLEARED", "APPROVED", "COMMITTED"}


def _get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if not p:
        raise not_found("Program not found")
    return p


@bp.route("/api/v1/applications", methods=["POST"])
def create_application():
    user_id, role = get_auth()
    require_role(role, ["Student"])

    body = request.get_json(silent=True) or {}
    student_id = require_string(body, "student_id")
    program_id = require_string(body, "program_id")

    # student ownership: X-User-ID must equal student_id
    check_student_ownership(user_id, role, student_id)

    # existence of referenced program (tier 9: missing -> 404)
    program = db.programs.get(program_id)
    if not program:
        raise not_found("Program not found")

    # student must exist (body reference)
    student = db.students.get(student_id)
    if not student:
        raise not_found("Student not found")

    # state gate: program must be OPEN (tier 5/9)
    if program["status"] != "OPEN":
        raise invalid_state("Program is not OPEN")

    # temporal: deadline (tier 8)
    clock = parse_dt(get_clock(), "clock")
    deadline = parse_dt(program["application_deadline"], "application_deadline")
    if clock > deadline:
        raise ApiError(ERR_APPLICATION_DEADLINE_PASSED, "Application deadline has passed", 422)

    # domain constraints (tier 10): gpa, conduct, duplicate
    if student["gpa"] < program["min_gpa"]:
        raise ApiError(ERR_GPA_BELOW_MINIMUM, "Student GPA below program minimum", 422)
    if student["conduct_standing"] == "CONDUCT_HOLD":
        raise ApiError(ERR_CONDUCT_HOLD, "Student is on conduct hold", 422)

    for a in db.applications.values():
        if a["student_id"] == student_id and a["program_id"] == program_id and a["status"] in ACTIVE_APP_STATUSES:
            raise ApiError(ERR_DUPLICATE_APPLICATION, "An active application already exists for this student and program", 409)

    ts = now_iso()
    rec = {
        "id": new_id(),
        "student_id": student_id,
        "program_id": program_id,
        "aid_award_cents_snapshot": student["aid_award_cents"],
        "status": "SUBMITTED",
        "clearance_recorded_by": None,
        "approved_by": None,
        "withdraw_reason": None,
        "transfer_credits_posted": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.applications[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/applications", methods=["GET"])
def list_applications():
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    limit, offset = parse_pagination(request.args)
    student_id = request.args.get("student_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")

    items = list(db.applications.values())
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]

    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(a) for a in page], limit, offset, total)


@bp.route("/api/v1/applications/<id>", methods=["GET"])
def get_application(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator", "Student"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")
    check_student_ownership(user_id, role, rec["student_id"])
    return success_object(dict(rec), 200)


@bp.route("/api/v1/applications/<id>/clearance", methods=["POST"])
def clearance(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")

    body = request.get_json(silent=True) or {}
    decision = require_enum(body, "decision", {"CLEARED", "RETURNED_FOR_REVISION", "REJECTED"})

    if rec["status"] != "SUBMITTED":
        raise invalid_state("Application is not in SUBMITTED status")

    rec["status"] = decision
    rec["clearance_recorded_by"] = user_id
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)


@bp.route("/api/v1/applications/<id>/resubmit", methods=["POST"])
def resubmit(id):
    user_id, role = get_auth()
    require_role(role, ["Student"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, rec["student_id"])

    if rec["status"] != "RETURNED_FOR_REVISION":
        raise invalid_state("Application is not in RETURNED_FOR_REVISION status")

    rec["status"] = "SUBMITTED"
    rec["clearance_recorded_by"] = None
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)


@bp.route("/api/v1/applications/<id>/approve", methods=["POST"])
def approve(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")

    # state gate (tier 5)
    if rec["status"] != "CLEARED":
        raise invalid_state("Application is not in CLEARED status")

    program = _get_program_or_404(rec["program_id"])
    if program["status"] != "OPEN":
        raise invalid_state("Program is not OPEN")

    # segregation of duties (tier 6)
    if user_id == rec["clearance_recorded_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from clearance recorder", 403)

    # travel-warning gate (tier 7)
    clock = parse_dt(get_clock(), "clock")
    prog_start = parse_dt(program["start_date"], "start_date")
    prog_end = parse_dt(program["end_date"], "end_date")
    if active_blocking_advisory(program["country_code"], clock, prog_start, prog_end):
        raise ApiError(ERR_TRAVEL_ADVISORY_BLOCK, "Travel advisory blocks approval", 422)

    rec["status"] = "APPROVED"
    rec["approved_by"] = user_id
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)


@bp.route("/api/v1/applications/<id>/commit", methods=["POST"])
def commit(id):
    user_id, role = get_auth()
    require_role(role, ["Student"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, rec["student_id"])

    if rec["status"] != "APPROVED":
        raise invalid_state("Application is not in APPROVED status")

    program = _get_program_or_404(rec["program_id"])
    if program["status"] != "OPEN":
        raise invalid_state("Program is not OPEN")

    # capacity check (tier 11)
    recompute_seats(program)
    if program["seats_taken"] >= program["capacity"]:
        raise ApiError(ERR_PROGRAM_FULL, "Program is full", 409)

    # commit
    rec["status"] = "COMMITTED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()

    recompute_seats(program)
    program["version"] += 1
    program["updated_at"] = now_iso()

    # create billing statement
    agreement = db.partner_agreements.get(program["partner_agreement_id"])
    create_billing_statement(rec, program, agreement)

    return success_object(dict(rec), 200)


@bp.route("/api/v1/applications/<id>/withdraw", methods=["POST"])
def withdraw(id):
    user_id, role = get_auth()
    require_role(role, ["Student", "ProgramCoordinator"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")

    # student ownership only applies to Student role; coordinator may withdraw any
    if role == "Student":
        check_student_ownership(user_id, role, rec["student_id"])

    if rec["status"] not in WITHDRAWABLE:
        raise invalid_state("Application cannot be withdrawn from its current status")

    reason = "STUDENT_INITIATED" if role == "Student" else "STAFF_INITIATED"
    withdraw_application(rec, reason)
    return success_object(dict(rec), 200)


@bp.route("/api/v1/applications/<id>/lifecycle", methods=["POST"])
def lifecycle(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    rec = db.applications.get(id)
    if not rec:
        raise not_found("Application not found")

    body = request.get_json(silent=True) or {}
    action = require_enum(body, "action", {"DEPART", "RECORD_RETURN"})

    program = _get_program_or_404(rec["program_id"])

    if action == "DEPART":
        if rec["status"] != "COMMITTED":
            raise invalid_state("Application is not in COMMITTED status")
        # insurance coverage check (tier 9 referential)
        prog_start = parse_dt(program["start_date"], "start_date")
        prog_end = parse_dt(program["end_date"], "end_date")
        covered = False
        for enr in db.insurance_enrollments.values():
            if enr["application_id"] != rec["id"] or enr["status"] != "ACTIVE":
                continue
            cs = parse_dt(enr["coverage_start_date"], "coverage_start_date")
            ce = parse_dt(enr["coverage_end_date"], "coverage_end_date")
            if cs <= prog_start and ce >= prog_end:
                covered = True
                break
        if not covered:
            raise ApiError(ERR_INSURANCE_COVERAGE_MISSING, "No ACTIVE insurance enrollment covering the program dates", 422)

        rec["status"] = "ABROAD"
        rec["version"] += 1
        rec["updated_at"] = now_iso()
        recompute_seats(program)
        return success_object(dict(rec), 200)

    else:  # RECORD_RETURN
        if rec["status"] != "ABROAD":
            raise invalid_state("Application is not in ABROAD status")
        rec["status"] = "RETURNED_HOME"
        rec["version"] += 1
        rec["updated_at"] = now_iso()
        recompute_seats(program)
        program["version"] += 1
        program["updated_at"] = now_iso()
        return success_object(dict(rec), 200)
