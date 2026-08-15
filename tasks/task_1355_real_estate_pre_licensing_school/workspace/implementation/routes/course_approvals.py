"""Course approval endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination, parse_date
from response import success_object, success_list
from datetime import timedelta

bp = Blueprint("course_approvals", __name__)


def _approval_to_json(a):
    return {k: v for k, v in a.items()}


def _get_course(course_id):
    course = db.courses.get(course_id)
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course {course_id} not found")
    return course


def _get_approval(approval_id):
    approval = db.course_approvals.get(approval_id)
    if not approval:
        errors.raise_error(errors.ERR_APPROVAL_NOT_FOUND, f"Approval {approval_id} not found")
    return approval


def _check_school_probation(course):
    """School posture must be GOOD_STANDING for approval submissions/renewals."""
    school = db.schools.get(course["school_id"])
    if school and school.get("posture") == "PROBATION":
        errors.raise_error(errors.ERR_SCHOOL_ON_PROBATION,
                           "School is on PROBATION")


def _resume_suspended_grants(course_id, state_code):
    """When approval becomes APPROVED, resume suspended grants for this course+state."""
    for grant in db.equivalency_grants.values():
        if (grant["course_id"] == course_id
                and grant["home_state_code"] == state_code
                and grant["status"] == "SUSPENDED"):
            grant["status"] = "ACTIVE"
            db.touch(grant)
            db.audit("EquivalencyGrant", grant["id"], "STATUS_CHANGE",
                     "system", "system",
                     {"from_status": "SUSPENDED", "to_status": "ACTIVE"})


def _suspend_active_grants(course_id, state_code):
    """When approval becomes EXPIRED, suspend active grants."""
    for grant in db.equivalency_grants.values():
        if (grant["course_id"] == course_id
                and grant["home_state_code"] == state_code
                and grant["status"] == "ACTIVE"):
            grant["status"] = "SUSPENDED"
            db.touch(grant)
            db.audit("EquivalencyGrant", grant["id"], "STATUS_CHANGE",
                     "system", "system",
                     {"from_status": "ACTIVE", "to_status": "SUSPENDED"})


@bp.route("/courses/<course_id>/approvals", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_course_approval(course_id):
    course = _get_course(course_id)
    _check_school_probation(course)

    body = get_json_body(required_fields=["state_code"])
    auth = request.auth

    # Singleton check
    for a in db.course_approvals.values():
        if a["course_id"] == course_id and a["state_code"] == body["state_code"]:
            errors.raise_error(errors.ERR_APPROVAL_ALREADY_EXISTS,
                               f"Approval already exists for course+state")

    approval = db.new_entity({
        "course_id": course_id,
        "state_code": body["state_code"],
        "application_round": 1,
        "status": "PENDING",
        "valid_from": None,
        "valid_until": None,
        "decided_at": None,
    })
    db.course_approvals[approval["id"]] = approval
    db.audit("CourseApproval", approval["id"], "APPROVAL_SUBMITTED",
             auth["role"], auth["user_id"])
    return success_object(_approval_to_json(approval), 201)


@bp.route("/courses/<course_id>/approvals", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_course_approvals(course_id):
    _get_course(course_id)
    limit, offset = parse_pagination()
    items = [a for a in db.course_approvals.values() if a["course_id"] == course_id]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_approval_to_json(a) for a in page], limit, offset, total)


@bp.route("/approvals/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def get_approval(id):
    approval = _get_approval(id)
    return success_object(_approval_to_json(approval))


@bp.route("/approvals/<id>/decide", methods=["POST"])
@require_roles("StateCommission")
def decide_approval(id):
    approval = _get_approval(id)
    body = get_json_body(
        required_fields=["decision"],
        optional_fields=["valid_from", "valid_until"],
    )
    auth = request.auth

    if approval["status"] not in ("PENDING", "RENEWAL_PENDING"):
        errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                           f"Approval status is {approval['status']}, expected PENDING or RENEWAL_PENDING")

    decision = body["decision"]
    if decision not in ("APPROVED", "DENIED"):
        errors.raise_error(errors.ERR_INVALID_ENUM, f"Invalid decision: {decision}")

    if decision == "APPROVED":
        valid_from_str = body.get("valid_from")
        valid_until_str = body.get("valid_until")
        if not valid_from_str or not valid_until_str:
            errors.raise_error(errors.ERR_INVALID_VALIDITY_WINDOW,
                               "valid_from and valid_until required for APPROVED decision")
        valid_from = parse_date(valid_from_str, "valid_from")
        valid_until = parse_date(valid_until_str, "valid_until")
        if valid_until < valid_from:
            errors.raise_error(errors.ERR_INVALID_VALIDITY_WINDOW,
                               "valid_until must be >= valid_from")

        old_status = approval["status"]
        is_renewal = old_status == "RENEWAL_PENDING"

        approval["status"] = "APPROVED"
        approval["valid_from"] = valid_from_str
        approval["valid_until"] = valid_until_str
        approval["decided_at"] = db.now_iso()
        if is_renewal:
            approval["application_round"] += 1
        db.touch(approval)
        db.audit("CourseApproval", approval["id"], "STATUS_CHANGE",
                 auth["role"], auth["user_id"],
                 {"from_status": old_status, "to_status": "APPROVED"})

        # Resume suspended grants
        _resume_suspended_grants(approval["course_id"], approval["state_code"])
    else:
        # DENIED
        old_status = approval["status"]
        is_renewal = old_status == "RENEWAL_PENDING"

        if is_renewal:
            approval["status"] = "EXPIRED"
            approval["decided_at"] = db.now_iso()
            # Suspend active grants
            _suspend_active_grants(approval["course_id"], approval["state_code"])
        else:
            approval["status"] = "DENIED"
            approval["decided_at"] = db.now_iso()

        db.touch(approval)
        db.audit("CourseApproval", approval["id"], "STATUS_CHANGE",
                 auth["role"], auth["user_id"],
                 {"from_status": old_status, "to_status": approval["status"]})

    return success_object(_approval_to_json(approval))


@bp.route("/approvals/<id>/resubmit", methods=["POST"])
@require_roles("ComplianceOfficer")
def resubmit_approval(id):
    approval = _get_approval(id)
    auth = request.auth

    if approval["status"] != "DENIED":
        errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                           f"Approval status is {approval['status']}, expected DENIED")

    approval["status"] = "PENDING"
    approval["application_round"] += 1
    approval["decided_at"] = None
    db.touch(approval)
    db.audit("CourseApproval", approval["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "DENIED", "to_status": "PENDING"})
    return success_object(_approval_to_json(approval))


@bp.route("/approvals/<id>/renew", methods=["POST"])
@require_roles("ComplianceOfficer")
def renew_approval(id):
    approval = _get_approval(id)
    auth = request.auth

    # Check school probation
    course = db.courses.get(approval["course_id"])
    if course:
        _check_school_probation(course)

    if approval["status"] == "EXPIRING":
        pass  # Can renew from EXPIRING
    elif approval["status"] == "EXPIRED":
        # Late renewal: within 30 days after valid_until
        from services.calculations import _extract_date
        valid_until = _extract_date(approval.get("valid_until"))
        if valid_until is None:
            errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                               "No valid_until on approval")
        today = db.today()
        if today > valid_until + timedelta(days=30):
            errors.raise_error(errors.ERR_APPROVAL_RENEWAL_WINDOW_CLOSED,
                               "Late renewal window closed (>30 days past valid_until)")
    else:
        errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                           f"Approval status is {approval['status']}, expected EXPIRING or EXPIRED")

    old_status = approval["status"]
    approval["status"] = "RENEWAL_PENDING"
    db.touch(approval)
    db.audit("CourseApproval", approval["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": "RENEWAL_PENDING"})
    return success_object(_approval_to_json(approval))
