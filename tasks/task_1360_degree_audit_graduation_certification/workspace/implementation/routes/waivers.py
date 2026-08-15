"""SubstitutionWaiver routes: file, list, get, advisor-decision,
registrar-decision, resubmit, revoke."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, parse_pagination, require_owner, require_roles
from response import success_list, success_object
from services.cascade import refresh_student_program_flag_and_conditional
from util import as_enum, as_number, as_str, json_body, make_resource, optional, paginate, require, touch

bp = Blueprint("waivers", __name__)

WAIVER_KINDS = ("SUBSTITUTION", "WAIVER")
DECISIONS = ("APPROVE", "DENY")


def _get_waiver_or_404(waiver_id):
    w = db.substitution_waivers.get(waiver_id)
    if w is None:
        raise ApiError("ERR_WAIVER_NOT_FOUND", "SubstitutionWaiver not found.")
    return w


def _check_owner_for_student_role(user_id, role, waiver):
    if role == "Student":
        sp = db.student_programs[waiver["student_program_id"]]
        require_owner(user_id, sp["student_id"])


# ---------------------------------------------------------------------------
# POST /student-programs/{id}/waivers
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>/waivers", methods=["POST"])
def create_waiver(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("Advisor", "Student"))
    sp = db.student_programs.get(sp_id)
    if sp is None:
        raise ApiError("ERR_STUDENT_PROGRAM_NOT_FOUND", "StudentProgram not found.")
    if role == "Student":
        require_owner(user_id, sp["student_id"])
    body = json_body()

    requirement_group_id = require(body, "requirement_group_id")
    rg = db.requirement_groups.get(requirement_group_id)
    if rg is None:
        raise ApiError(
            "ERR_REQUIREMENT_GROUP_NOT_FOUND", "RequirementGroup not found."
        )
    kind = as_enum(require(body, "kind"), "kind", WAIVER_KINDS)
    enrollment_id = optional(body, "enrollment_id", None)
    credit_waiver_amount = optional(body, "credit_waiver_amount", None)
    reason = optional(body, "reason", None)

    if kind == "SUBSTITUTION":
        if not enrollment_id:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "SUBSTITUTION requires enrollment_id.",
            )
        enrollment = db.enrollments.get(enrollment_id)
        if enrollment is None:
            raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "Enrollment not found.")
    if kind == "WAIVER":
        if credit_waiver_amount is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "WAIVER requires credit_waiver_amount.",
            )
        credit_waiver_amount = as_number(credit_waiver_amount, "credit_waiver_amount")

    if sp["status"] != "ACTIVE":
        raise ApiError(
            "ERR_STUDENT_PROGRAM_NOT_ACTIVE", "StudentProgram must be ACTIVE."
        )

    requested_by_role = "STUDENT" if role == "Student" else "ADVISOR"
    waiver = make_resource(
        {
            "student_program_id": sp["id"],
            "requirement_group_id": rg["id"],
            "kind": kind,
            "enrollment_id": enrollment_id if kind == "SUBSTITUTION" else None,
            "credit_waiver_amount": credit_waiver_amount if kind == "WAIVER" else None,
            "reason": reason,
            "requested_by_role": requested_by_role,
            "requested_by_user_id": user_id,
            "status": "SUBMITTED",
            "decision_reason": None,
        }
    )
    db.substitution_waivers[waiver["id"]] = waiver
    return success_object(waiver, 201)


# ---------------------------------------------------------------------------
# GET /substitution-waivers  (filters)
# ---------------------------------------------------------------------------


@bp.route("/substitution-waivers", methods=["GET"])
def list_waivers():
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor"))
    limit, offset = parse_pagination()

    items = list(db.substitution_waivers.values())
    sp_id = request.args.get("student_program_id")
    rg_id = request.args.get("requirement_group_id")
    enr_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    rbu = request.args.get("requested_by_user_id")
    if sp_id:
        items = [w for w in items if w["student_program_id"] == sp_id]
    if rg_id:
        items = [w for w in items if w["requirement_group_id"] == rg_id]
    if enr_id:
        items = [w for w in items if w["enrollment_id"] == enr_id]
    if status:
        items = [w for w in items if w["status"] == status]
    if rbu:
        items = [w for w in items if w["requested_by_user_id"] == rbu]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /substitution-waivers/{id}
# ---------------------------------------------------------------------------


@bp.route("/substitution-waivers/<waiver_id>", methods=["GET"])
def get_waiver(waiver_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    w = _get_waiver_or_404(waiver_id)
    _check_owner_for_student_role(user_id, role, w)
    return success_object(w)


# ---------------------------------------------------------------------------
# POST /substitution-waivers/{id}/advisor-decision
# ---------------------------------------------------------------------------


@bp.route("/substitution-waivers/<waiver_id>/advisor-decision", methods=["POST"])
def advisor_decision(waiver_id):
    user_id, role = get_auth()
    require_roles(role, ("Advisor",))
    w = _get_waiver_or_404(waiver_id)
    body = json_body()
    decision = as_enum(require(body, "decision"), "decision", DECISIONS)
    decision_reason = optional(body, "decision_reason", None)

    if w["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_WAIVER_INVALID_STATE", "Waiver must be SUBMITTED for advisor decision."
        )

    # Segregation of duties (priority 7)
    if w["requested_by_role"] == "ADVISOR" and w["requested_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SELF_APPROVAL_FORBIDDEN",
            "Advisor may not decide an exception they requested.",
        )

    # Substitution requires COMPLETED enrollment
    if w["kind"] == "SUBSTITUTION":
        enrollment = db.enrollments.get(w["enrollment_id"])
        if enrollment is None:
            raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "Enrollment not found.")
        if enrollment["status"] != "COMPLETED":
            raise ApiError(
                "ERR_ENROLLMENT_NOT_COMPLETED",
                "Substitution requires the enrollment to be COMPLETED.",
            )

    if decision == "APPROVE":
        w["status"] = "ADVISOR_APPROVED"
    else:
        w["status"] = "DENIED"
        w["decision_reason"] = decision_reason
    touch(w)
    return success_object(w)


# ---------------------------------------------------------------------------
# POST /substitution-waivers/{id}/registrar-decision
# ---------------------------------------------------------------------------


@bp.route("/substitution-waivers/<waiver_id>/registrar-decision", methods=["POST"])
def registrar_decision(waiver_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    w = _get_waiver_or_404(waiver_id)
    body = json_body()
    decision = as_enum(require(body, "decision"), "decision", DECISIONS)
    decision_reason = optional(body, "decision_reason", None)

    if w["status"] != "ADVISOR_APPROVED":
        raise ApiError(
            "ERR_WAIVER_INVALID_STATE",
            "Waiver must be ADVISOR_APPROVED for registrar decision.",
        )

    if w["kind"] == "SUBSTITUTION":
        enrollment = db.enrollments.get(w["enrollment_id"])
        if enrollment is None:
            raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "Enrollment not found.")
        if enrollment["status"] != "COMPLETED":
            raise ApiError(
                "ERR_ENROLLMENT_NOT_COMPLETED",
                "Substitution requires the enrollment to be COMPLETED.",
            )

    if decision == "APPROVE":
        w["status"] = "APPROVED"
        touch(w)
        sp = db.student_programs[w["student_program_id"]]
        refresh_student_program_flag_and_conditional(sp["student_id"], sp["id"])
    else:
        w["status"] = "DENIED"
        w["decision_reason"] = decision_reason
        touch(w)
    return success_object(w)


# ---------------------------------------------------------------------------
# POST /substitution-waivers/{id}/resubmit
# ---------------------------------------------------------------------------


@bp.route("/substitution-waivers/<waiver_id>/resubmit", methods=["POST"])
def resubmit_waiver(waiver_id):
    user_id, role = get_auth()
    require_roles(role, ("Advisor", "Student"))
    w = _get_waiver_or_404(waiver_id)
    _check_owner_for_student_role(user_id, role, w)

    if w["status"] != "DENIED":
        raise ApiError(
            "ERR_WAIVER_INVALID_STATE", "Waiver must be DENIED to resubmit."
        )

    body = json_body() if request.data else {}
    enrollment_id = optional(body, "enrollment_id", None)
    credit_waiver_amount = optional(body, "credit_waiver_amount", None)
    reason = optional(body, "reason", None)

    if enrollment_id is not None:
        enrollment = db.enrollments.get(enrollment_id)
        if enrollment is None:
            raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "Enrollment not found.")
        w["enrollment_id"] = enrollment_id
    if credit_waiver_amount is not None:
        w["credit_waiver_amount"] = as_number(credit_waiver_amount, "credit_waiver_amount")
    if reason is not None:
        w["reason"] = reason

    # Validate kind-shape after optional edits
    if w["kind"] == "SUBSTITUTION" and not w["enrollment_id"]:
        raise ApiError("ERR_INVALID_REQUEST", "SUBSTITUTION requires enrollment_id.")
    if w["kind"] == "WAIVER" and w["credit_waiver_amount"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "WAIVER requires credit_waiver_amount.")

    # requested_by_role / requested_by_user_id are preserved (original requester).
    w["status"] = "SUBMITTED"
    w["decision_reason"] = None
    touch(w)
    return success_object(w)


# ---------------------------------------------------------------------------
# POST /substitution-waivers/{id}/revoke
# ---------------------------------------------------------------------------


@bp.route("/substitution-waivers/<waiver_id>/revoke", methods=["POST"])
def revoke_waiver(waiver_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    w = _get_waiver_or_404(waiver_id)
    body = json_body()
    reason = require(body, "reason")

    if w["status"] != "APPROVED":
        raise ApiError(
            "ERR_WAIVER_INVALID_STATE", "Waiver must be APPROVED to revoke."
        )
    w["status"] = "REVOKED"
    w["decision_reason"] = reason
    touch(w)
    sp = db.student_programs[w["student_program_id"]]
    refresh_student_program_flag_and_conditional(sp["student_id"], sp["id"])
    return success_object(w)
