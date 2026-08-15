"""StudentProgram routes + audit creation/listing."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, parse_pagination, require_owner, require_roles
from response import success_list, success_object
from services.audit import compute_audit
from util import as_enum, as_int, json_body, make_resource, paginate, require, optional, touch

bp = Blueprint("student_programs", __name__)

AUDIT_KINDS = ("STANDARD", "WHAT_IF", "CONDITIONAL", "FINAL")


def _get_student_program_or_404(sp_id):
    sp = db.student_programs.get(sp_id)
    if sp is None:
        raise ApiError("ERR_STUDENT_PROGRAM_NOT_FOUND", "StudentProgram not found.")
    return sp


def _check_student_owner(user_id, role, sp):
    if role == "Student":
        require_owner(user_id, sp["student_id"])


# ---------------------------------------------------------------------------
# POST /students/{id}/programs  (declare a major)
# ---------------------------------------------------------------------------


@bp.route("/students/<student_id>/programs", methods=["POST"])
def declare_program(student_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Student"))
    student = db.students.get(student_id)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND", "Student not found.")
    if role == "Student":
        require_owner(user_id, student["id"])
    body = json_body()

    program_id = require(body, "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "Program not found.")
    catalog_year = as_int(require(body, "catalog_year"), "catalog_year")

    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_RETIRED", "Program is RETIRED.")
    if not (program["catalog_year_start"] <= catalog_year < program["catalog_year_end"]):
        raise ApiError(
            "ERR_CATALOG_YEAR_OUT_OF_RANGE",
            "catalog_year outside the program's catalog range.",
        )

    sp = make_resource(
        {
            "student_id": student["id"],
            "program_id": program["id"],
            "catalog_year": catalog_year,
            "status": "ACTIVE",
            "latest_audit_satisfied": False,
        }
    )
    db.student_programs[sp["id"]] = sp
    return success_object(sp, 201)


# ---------------------------------------------------------------------------
# GET /student-programs  (filters: student_id, program_id, status)
# ---------------------------------------------------------------------------


@bp.route("/student-programs", methods=["GET"])
def list_student_programs():
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    limit, offset = parse_pagination()

    items = list(db.student_programs.values())
    if role == "Student":
        items = [sp for sp in items if sp["student_id"] == user_id]
    student_id = request.args.get("student_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if student_id:
        items = [sp for sp in items if sp["student_id"] == student_id]
    if program_id:
        items = [sp for sp in items if sp["program_id"] == program_id]
    if status:
        items = [sp for sp in items if sp["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /student-programs/{id}
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>", methods=["GET"])
def get_student_program(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    sp = _get_student_program_or_404(sp_id)
    _check_student_owner(user_id, role, sp)
    return success_object(sp)


# ---------------------------------------------------------------------------
# POST /student-programs/{id}/withdraw
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>/withdraw", methods=["POST"])
def withdraw_student_program(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Student"))
    sp = _get_student_program_or_404(sp_id)
    _check_student_owner(user_id, role, sp)
    if sp["status"] != "ACTIVE":
        raise ApiError(
            "ERR_STUDENT_PROGRAM_NOT_ACTIVE", "StudentProgram must be ACTIVE."
        )
    sp["status"] = "WITHDRAWN"
    touch(sp)
    return success_object(sp)


# ---------------------------------------------------------------------------
# POST /student-programs/{id}/audits  (the OCC-protected write)
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>/audits", methods=["POST"])
def create_audit(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    sp = _get_student_program_or_404(sp_id)
    _check_student_owner(user_id, role, sp)
    body = json_body()

    audit_kind = as_enum(require(body, "audit_kind"), "audit_kind", AUDIT_KINDS)
    if audit_kind in ("FINAL", "CONDITIONAL") and role != "RegistrarStaff":
        raise ApiError(
            "ERR_FORBIDDEN", "FINAL and CONDITIONAL audits are RegistrarStaff-only."
        )

    target_program_id = optional(body, "target_program_id", None)
    if audit_kind == "WHAT_IF":
        if not target_program_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "target_program_id is required for WHAT_IF audits.",
            )
    else:
        # Non-WHAT_IF audits evaluate the declaration's own program.
        target_program_id = sp["program_id"]

    expected_version = require(body, "expected_student_program_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "expected_student_program_version must be an integer.",
        )

    # Existence of target program (body FK)
    target_program = db.programs.get(target_program_id)
    if target_program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "Target program not found.")

    # From-state
    if sp["status"] != "ACTIVE":
        raise ApiError(
            "ERR_STUDENT_PROGRAM_NOT_ACTIVE", "StudentProgram must be ACTIVE."
        )

    # OCC (priority 6)
    if sp["version"] != expected_version:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_student_program_version does not match StudentProgram.version.",
        )

    # Referenced-entity state for WHAT_IF target
    if audit_kind == "WHAT_IF":
        if target_program["status"] != "ACTIVE":
            raise ApiError("ERR_PROGRAM_RETIRED", "What-if target program is RETIRED.")
        if not (
            target_program["catalog_year_start"]
            <= sp["catalog_year"]
            < target_program["catalog_year_end"]
        ):
            raise ApiError(
                "ERR_CATALOG_YEAR_OUT_OF_RANGE",
                "What-if target does not cover the declaration's catalog year.",
            )

    student = db.students[sp["student_id"]]
    result = compute_audit(student, sp, target_program, audit_kind)

    # Supersede prior CURRENT audit of same kind (and same target for WHAT_IF)
    for a in db.degree_audits.values():
        if a["student_program_id"] != sp["id"] or a["status"] != "CURRENT":
            continue
        if a["audit_kind"] != audit_kind:
            continue
        if audit_kind == "WHAT_IF" and a["target_program_id"] != target_program_id:
            continue
        a["status"] = "SUPERSEDED"
        touch(a)

    audit = make_resource(
        {
            "student_program_id": sp["id"],
            "audit_kind": audit_kind,
            "target_program_id": target_program_id,
            "catalog_year_used": sp["catalog_year"],
            "status": "CURRENT",
            "total_credits_applied": result["total_credits_applied"],
            "in_progress_credits_counted": result["in_progress_credits_counted"],
            "outstanding_credits": result["outstanding_credits"],
            "gpa_at_audit": result["gpa_at_audit"],
            "overall_satisfied": result["overall_satisfied"],
            "groups_result": result["groups_result"],
        }
    )
    db.degree_audits[audit["id"]] = audit

    # Audit creation increments the declaration version by 1; FINAL refreshes
    # latest_audit_satisfied (which may itself be the source of the bump).
    if audit_kind == "FINAL":
        if sp["latest_audit_satisfied"] != result["overall_satisfied"]:
            sp["latest_audit_satisfied"] = result["overall_satisfied"]
    touch(sp)

    return success_object(audit, 201)


# ---------------------------------------------------------------------------
# GET /student-programs/{id}/audits
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>/audits", methods=["GET"])
def list_audits(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    sp = _get_student_program_or_404(sp_id)
    _check_student_owner(user_id, role, sp)
    limit, offset = parse_pagination()

    items = [a for a in db.degree_audits.values() if a["student_program_id"] == sp["id"]]
    audit_kind = request.args.get("audit_kind")
    status = request.args.get("status")
    target_program_id = request.args.get("target_program_id")
    if audit_kind:
        items = [a for a in items if a["audit_kind"] == audit_kind]
    if status:
        items = [a for a in items if a["status"] == status]
    if target_program_id:
        items = [a for a in items if a["target_program_id"] == target_program_id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
