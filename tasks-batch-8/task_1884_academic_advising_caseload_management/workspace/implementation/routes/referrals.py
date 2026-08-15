"""Early-alert referral endpoints: intake, list, get, outreach, escalate, close."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, require_enum,
    stamp_new, touch,
)
from services.calculations import (
    MAX_ATTEMPTS, compute_due_at, compute_is_sla_breached,
    get_assigned_advisor_id, recompute_student_risk,
)

bp = Blueprint("referrals", __name__)

ROLE_READ = ("AdvisingDirector", "Advisor", "FacultyReferrer")
WORKING_STATES = ("OPEN", "OUTREACH_IN_PROGRESS", "NO_RESPONSE")


def referral_public(r):
    r["is_sla_breached"] = compute_is_sla_breached(r, db.get_logical_clock_iso())
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "source": r["source"],
        "severity": r["severity"],
        "reason": r["reason"],
        "status": r["status"],
        "attempt_count": r["attempt_count"],
        "due_at": r["due_at"],
        "is_sla_breached": r["is_sla_breached"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _check_ownership(role, user_id, student_id):
    """Advisor-role callers must be the student's assigned advisor."""
    if role == "Advisor":
        assigned = get_assigned_advisor_id(student_id)
        if assigned != user_id:
            raise ApiError(errors.ERR_NOT_ASSIGNED_ADVISOR,
                           "Caller is not the student's assigned advisor", 403)


def _run_escalation_cascade(referral):
    """Create the cascade Intervention and fire the risk chain."""
    student_id = referral["student_id"]
    intervention = stamp_new({
        "student_id": student_id,
        "referral_id": referral["id"],
        "intervention_type": "ACADEMIC_COACHING",
        "note": None,
        "status": "OPEN",
        "outcome": None,
    })
    db.interventions[intervention["id"]] = intervention
    recompute_student_risk(student_id)


@bp.route("/advising/referrals", methods=["POST"])
def create_referral():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["student_id", "source", "severity", "reason"])
    require_enum(data["source"], ("FACULTY", "STAFF"), "source")
    require_enum(data["severity"], ("LOW", "MEDIUM", "HIGH"), "severity")
    require_role(role, ("FacultyReferrer", "AdvisingDirector"))
    student = db.students.get(data["student_id"])
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {data['student_id']} not found", 404)

    referral = stamp_new({
        "student_id": student["id"],
        "source": data["source"],
        "severity": data["severity"],
        "reason": data["reason"],
        "status": "OPEN",
        "attempt_count": 0,
    })
    referral["due_at"] = compute_due_at(referral["created_at"], referral["severity"])
    referral["is_sla_breached"] = False
    db.referrals[referral["id"]] = referral
    recompute_student_risk(student["id"])
    return success_object(referral_public(referral), 201)


@bp.route("/advising/referrals", methods=["GET"])
def list_referrals():
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    limit, offset = get_pagination_params()
    items = list(db.referrals.values())
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    breached = request.args.get("is_sla_breached")
    if student_id is not None:
        items = [r for r in items if r["student_id"] == student_id]
    if status is not None:
        if status not in ("OPEN", "OUTREACH_IN_PROGRESS", "NO_RESPONSE", "RESPONDED",
                          "ESCALATED", "CLOSED"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [r for r in items if r["status"] == status]
    if severity is not None:
        if severity not in ("LOW", "MEDIUM", "HIGH"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid severity filter: {severity}", 400)
        items = [r for r in items if r["severity"] == severity]
    if breached is not None:
        want = breached.lower() in ("true", "1", "yes")
        now_iso = db.get_logical_clock_iso()
        items = [r for r in items if compute_is_sla_breached(r, now_iso) == want]
    page, total = paginate(items, limit, offset)
    return success_list([referral_public(r) for r in page], limit, offset, total)


@bp.route("/advising/referrals/<referralId>", methods=["GET"])
def get_referral(referralId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    referral = db.referrals.get(referralId)
    if not referral:
        raise ApiError(errors.ERR_REFERRAL_NOT_FOUND, f"Referral {referralId} not found", 404)
    return success_object(referral_public(referral))


@bp.route("/advising/referrals/<referralId>/outreach", methods=["POST"])
def outreach(referralId):
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["outcome"])
    require_enum(data["outcome"], ("NO_ANSWER", "REACHED"), "outcome")
    require_role(role, ("Advisor", "AdvisingDirector"))
    referral = db.referrals.get(referralId)
    if not referral:
        raise ApiError(errors.ERR_REFERRAL_NOT_FOUND, f"Referral {referralId} not found", 404)
    if referral["status"] not in WORKING_STATES:
        raise ApiError(errors.ERR_REFERRAL_INVALID_STATE,
                       "Outreach is allowed only from OPEN, OUTREACH_IN_PROGRESS, or NO_RESPONSE", 409)
    _check_ownership(role, user_id, referral["student_id"])

    outcome = data["outcome"]
    new_count = referral["attempt_count"] + 1
    if outcome == "REACHED":
        referral["attempt_count"] = new_count
        referral["status"] = "RESPONDED"
        touch(referral)
        recompute_student_risk(referral["student_id"])
        return success_object(referral_public(referral))

    # NO_ANSWER
    if new_count >= MAX_ATTEMPTS:
        # auto-escalation: attempt_count set to MAX_ATTEMPTS as part of the same call
        referral["attempt_count"] = MAX_ATTEMPTS
        referral["status"] = "ESCALATED"
        touch(referral)
        _run_escalation_cascade(referral)
        return success_object(referral_public(referral))

    referral["attempt_count"] = new_count
    # NO_ANSWER cycle: OPEN -> OUTREACH_IN_PROGRESS -> NO_RESPONSE -> OUTREACH_IN_PROGRESS
    if referral["status"] == "OPEN":
        referral["status"] = "OUTREACH_IN_PROGRESS"
    elif referral["status"] == "OUTREACH_IN_PROGRESS":
        referral["status"] = "NO_RESPONSE"
    else:  # NO_RESPONSE
        referral["status"] = "OUTREACH_IN_PROGRESS"
    touch(referral)
    return success_object(referral_public(referral))


@bp.route("/advising/referrals/<referralId>/escalate", methods=["POST"])
def escalate(referralId):
    user_id, role = get_auth_context()
    require_role(role, ("AdvisingDirector",))
    referral = db.referrals.get(referralId)
    if not referral:
        raise ApiError(errors.ERR_REFERRAL_NOT_FOUND, f"Referral {referralId} not found", 404)
    if referral["status"] not in WORKING_STATES:
        raise ApiError(errors.ERR_REFERRAL_INVALID_STATE,
                       "Escalation is allowed only from OPEN, OUTREACH_IN_PROGRESS, or NO_RESPONSE", 409)
    referral["status"] = "ESCALATED"
    touch(referral)
    _run_escalation_cascade(referral)
    return success_object(referral_public(referral))


@bp.route("/advising/referrals/<referralId>/close", methods=["POST"])
def close_referral(referralId):
    user_id, role = get_auth_context()
    require_role(role, ("Advisor", "AdvisingDirector"))
    referral = db.referrals.get(referralId)
    if not referral:
        raise ApiError(errors.ERR_REFERRAL_NOT_FOUND, f"Referral {referralId} not found", 404)
    if referral["status"] not in ("RESPONDED", "ESCALATED"):
        raise ApiError(errors.ERR_REFERRAL_INVALID_STATE,
                       "Only a RESPONDED or ESCALATED referral may be closed", 409)
    _check_ownership(role, user_id, referral["student_id"])
    referral["status"] = "CLOSED"
    touch(referral)
    recompute_student_risk(referral["student_id"])
    return success_object(referral_public(referral))
