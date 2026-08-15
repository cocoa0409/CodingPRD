"""GraduationApplication routes + conferral + diploma reissue."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, parse_pagination, require_owner, require_roles
from response import success_list, success_object
from services.honors import compute_honors_designation, find_covering_policy
from util import (
    as_enum,
    as_iso_date,
    as_str,
    json_body,
    make_resource,
    optional,
    paginate,
    parse_iso8601,
    require,
    touch,
)

bp = Blueprint("applications", __name__)

DECISIONS = ("CLEARED", "CONDITIONALLY_CLEARED", "DENIED")
FILING_LEAD_DAYS = 30
LIVE_APPLICATION_STATES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CLEARED", "CONDITIONALLY_CLEARED")


def _get_application_or_404(app_id):
    a = db.graduation_applications.get(app_id)
    if a is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "GraduationApplication not found.")
    return a


def _check_owner(user_id, role, app):
    if role == "Student":
        sp = db.student_programs[app["student_program_id"]]
        require_owner(user_id, sp["student_id"])


def _current_final_audit(sp_id):
    return next(
        (
            a
            for a in db.degree_audits.values()
            if a["student_program_id"] == sp_id
            and a["audit_kind"] == "FINAL"
            and a["status"] == "CURRENT"
        ),
        None,
    )


# ---------------------------------------------------------------------------
# POST /student-programs/{id}/applications
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>/applications", methods=["POST"])
def create_application(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("Student",))
    sp = db.student_programs.get(sp_id)
    if sp is None:
        raise ApiError("ERR_STUDENT_PROGRAM_NOT_FOUND", "StudentProgram not found.")
    require_owner(user_id, sp["student_id"])
    body = json_body()

    expected_term = as_str(require(body, "expected_term"), "expected_term")
    expected_conferral_date = as_iso_date(
        require(body, "expected_conferral_date"), "expected_conferral_date"
    )
    diploma_name = optional(body, "diploma_name", None)
    if diploma_name is not None:
        diploma_name = as_str(diploma_name, "diploma_name")

    if sp["status"] != "ACTIVE":
        raise ApiError(
            "ERR_STUDENT_PROGRAM_NOT_ACTIVE", "StudentProgram must be ACTIVE."
        )

    app = make_resource(
        {
            "student_program_id": sp["id"],
            "expected_term": expected_term,
            "expected_conferral_date": expected_conferral_date,
            "diploma_name": diploma_name,
            "status": "DRAFT",
            "decision_reason": None,
            "honors_designation": None,
            "conferred_at": None,
        }
    )
    db.graduation_applications[app["id"]] = app
    return success_object(app, 201)


# ---------------------------------------------------------------------------
# GET /student-programs/{id}/applications
# ---------------------------------------------------------------------------


@bp.route("/student-programs/<sp_id>/applications", methods=["GET"])
def list_applications(sp_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    sp = db.student_programs.get(sp_id)
    if sp is None:
        raise ApiError("ERR_STUDENT_PROGRAM_NOT_FOUND", "StudentProgram not found.")
    if role == "Student":
        require_owner(user_id, sp["student_id"])
    limit, offset = parse_pagination()

    items = [
        a for a in db.graduation_applications.values() if a["student_program_id"] == sp["id"]
    ]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /applications/{id}
# ---------------------------------------------------------------------------


@bp.route("/applications/<app_id>", methods=["GET"])
def get_application(app_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    app = _get_application_or_404(app_id)
    _check_owner(user_id, role, app)
    return success_object(app)


# ---------------------------------------------------------------------------
# POST /applications/{id}/submit
# ---------------------------------------------------------------------------


@bp.route("/applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    user_id, role = get_auth()
    require_roles(role, ("Student",))
    app = _get_application_or_404(app_id)
    _check_owner(user_id, role, app)
    sp = db.student_programs[app["student_program_id"]]
    student = db.students[sp["student_id"]]

    if app["status"] != "DRAFT":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE", "Application must be DRAFT to submit."
        )

    # Active application uniqueness (other live app for the same declaration)
    for other in db.graduation_applications.values():
        if other["id"] == app["id"]:
            continue
        if (
            other["student_program_id"] == sp["id"]
            and other["status"] in LIVE_APPLICATION_STATES
        ):
            raise ApiError(
                "ERR_ACTIVE_APPLICATION_EXISTS",
                "A non-terminal application already exists for the student-program.",
            )

    # Filing deadline: logical clock <= expected_conferral_date - 30 days
    now_dt = parse_iso8601(db.logical_clock_iso)
    conferral_dt = parse_iso8601(app["expected_conferral_date"] + "T00:00:00Z")
    deadline = conferral_dt - timedelta(days=FILING_LEAD_DAYS)
    if now_dt > deadline:
        raise ApiError(
            "ERR_FILING_DEADLINE_PASSED",
            "Filing deadline has passed.",
        )

    if student["financial_hold"]:
        raise ApiError("ERR_FINANCIAL_HOLD", "Student has a financial hold.")

    app["status"] = "SUBMITTED"
    touch(app)
    return success_object(app)


# ---------------------------------------------------------------------------
# POST /applications/{id}/begin-review
# ---------------------------------------------------------------------------


@bp.route("/applications/<app_id>/begin-review", methods=["POST"])
def begin_review(app_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    app = _get_application_or_404(app_id)
    sp = db.student_programs[app["student_program_id"]]
    student = db.students[sp["student_id"]]

    if app["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE", "Application must be SUBMITTED."
        )

    final_audit = _current_final_audit(sp["id"])
    if final_audit is None:
        raise ApiError(
            "ERR_FINAL_AUDIT_REQUIRED",
            "A CURRENT FINAL audit is required to begin review.",
        )

    if student["financial_hold"]:
        raise ApiError("ERR_FINANCIAL_HOLD", "Student has a financial hold.")

    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success_object(app)


# ---------------------------------------------------------------------------
# POST /applications/{id}/decide
# ---------------------------------------------------------------------------


@bp.route("/applications/<app_id>/decide", methods=["POST"])
def decide_application(app_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    app = _get_application_or_404(app_id)
    body = json_body()
    decision = as_enum(require(body, "decision"), "decision", DECISIONS)
    decision_reason = optional(body, "decision_reason", None)

    sp = db.student_programs[app["student_program_id"]]
    student = db.students[sp["student_id"]]

    if app["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE", "Application must be UNDER_REVIEW."
        )

    if decision == "CLEARED":
        final_audit = _current_final_audit(sp["id"])
        if final_audit is None or not final_audit["overall_satisfied"]:
            raise ApiError(
                "ERR_AUDIT_NOT_SATISFIED",
                "CURRENT FINAL audit overall_satisfied must be true.",
            )
        app["status"] = "CLEARED"
    elif decision == "CONDITIONALLY_CLEARED":
        in_progress = any(
            e["student_id"] == student["id"] and e["status"] == "IN_PROGRESS"
            for e in db.enrollments.values()
        )
        if not in_progress:
            raise ApiError(
                "ERR_NO_IN_PROGRESS_ENROLLMENTS",
                "At least one IN_PROGRESS enrollment is required.",
            )
        app["status"] = "CONDITIONALLY_CLEARED"
    else:  # DENIED
        app["status"] = "DENIED"
        app["decision_reason"] = decision_reason

    touch(app)
    return success_object(app)


# ---------------------------------------------------------------------------
# POST /applications/{id}/confer
# ---------------------------------------------------------------------------


@bp.route("/applications/<app_id>/confer", methods=["POST"])
def confer_application(app_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    app = _get_application_or_404(app_id)
    sp = db.student_programs[app["student_program_id"]]
    student = db.students[sp["student_id"]]
    program = db.programs[sp["program_id"]]

    if app["status"] != "CLEARED":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE", "Application must be CLEARED to confer."
        )

    policy = find_covering_policy(program["id"], sp["catalog_year"])
    if policy is None:
        raise ApiError(
            "ERR_HONORS_POLICY_MISSING",
            "No honors policy covers the declaration's catalog year.",
        )

    designation = compute_honors_designation(student, policy)
    app["honors_designation"] = designation
    app["conferred_at"] = db.logical_clock_iso
    app["status"] = "DEGREE_CONFERRED"
    touch(app)

    sp["status"] = "COMPLETED"
    touch(sp)

    student["status"] = "GRADUATED"
    touch(student)

    printed_name = app["diploma_name"] if app["diploma_name"] else student["legal_name"]
    diploma = make_resource(
        {
            "application_id": app["id"],
            "printed_name": printed_name,
            "conferral_date": app["expected_conferral_date"],
            "honors_designation": designation,
            "status": "PENDING",
            "reissue_of_diploma_id": None,
            "revocation_reason": None,
        }
    )
    db.diplomas[diploma["id"]] = diploma

    return success_object(app)


# ---------------------------------------------------------------------------
# POST /applications/{id}/diplomas/reissue
# ---------------------------------------------------------------------------


@bp.route("/applications/<app_id>/diplomas/reissue", methods=["POST"])
def reissue_diploma(app_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    app = _get_application_or_404(app_id)
    body = json_body()
    reason = require(body, "reason")
    printed_name = optional(body, "printed_name", None)
    conferral_date = optional(body, "conferral_date", None)

    if app["status"] != "DEGREE_CONFERRED":
        raise ApiError(
            "ERR_DIPLOMA_INVALID_STATE",
            "Reissue requires a DEGREE_CONFERRED application.",
        )

    # Latest diploma (most recent by created_at) must be REVOKED
    app_diplomas = [d for d in db.diplomas.values() if d["application_id"] == app["id"]]
    if not app_diplomas:
        raise ApiError(
            "ERR_DIPLOMA_INVALID_STATE", "No diploma exists for this application."
        )
    latest = max(app_diplomas, key=lambda d: (d["created_at"], d["id"]))
    if latest["status"] != "REVOKED":
        raise ApiError(
            "ERR_DIPLOMA_INVALID_STATE",
            "Latest diploma must be REVOKED to reissue.",
        )

    sp = db.student_programs[app["student_program_id"]]
    student = db.students[sp["student_id"]]
    program = db.programs[sp["program_id"]]
    policy = find_covering_policy(program["id"], sp["catalog_year"])
    if policy is None:
        raise ApiError(
            "ERR_HONORS_POLICY_MISSING",
            "No honors policy covers the declaration's catalog year.",
        )

    if printed_name is None:
        printed_name = app["diploma_name"] if app["diploma_name"] else student["legal_name"]
    if conferral_date is None:
        conferral_date = app["expected_conferral_date"]
    else:
        conferral_date = as_iso_date(conferral_date, "conferral_date")

    designation = compute_honors_designation(student, policy)

    diploma = make_resource(
        {
            "application_id": app["id"],
            "printed_name": printed_name,
            "conferral_date": conferral_date,
            "honors_designation": designation,
            "status": "PENDING",
            "reissue_of_diploma_id": latest["id"],
            "revocation_reason": None,
        }
    )
    db.diplomas[diploma["id"]] = diploma
    return success_object(diploma, 201)
