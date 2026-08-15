"""Instructor and instructor approval endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination, parse_date
from response import success_object, success_list
from datetime import timedelta

bp = Blueprint("instructors", __name__)


def _instructor_to_json(i):
    return {k: v for k, v in i.items()}


def _approval_to_json(a):
    return {k: v for k, v in a.items()}


# --- Instructor CRUD ---

@bp.route("/instructors", methods=["POST"])
@require_roles("Registrar")
def create_instructor():
    body = get_json_body(required_fields=["school_id", "full_name", "license_number"])
    auth = request.auth

    school = db.schools.get(body["school_id"])
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {body['school_id']} not found")

    # Uniqueness: license_number within school
    for i in db.instructors.values():
        if i["school_id"] == body["school_id"] and i["license_number"] == body["license_number"]:
            errors.raise_error(errors.ERR_DUPLICATE_INSTRUCTOR_LICENSE,
                               "license_number already exists in this school")

    instructor = db.new_entity({
        "school_id": body["school_id"],
        "full_name": body["full_name"],
        "license_number": body["license_number"],
    })
    db.instructors[instructor["id"]] = instructor
    db.audit("Instructor", instructor["id"], "INSTRUCTOR_CREATED",
             auth["role"], auth["user_id"])
    return success_object(_instructor_to_json(instructor), 201)


@bp.route("/instructors", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_instructors():
    limit, offset = parse_pagination()
    items = list(db.instructors.values())

    school_id = request.args.get("school_id")
    if school_id:
        items = [i for i in items if i["school_id"] == school_id]

    auth = request.auth
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        items = [i for i in items if i["school_id"] in own_school_ids]

    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_instructor_to_json(i) for i in page], limit, offset, total)


@bp.route("/instructors/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def get_instructor(id):
    instructor = db.instructors.get(id)
    if not instructor:
        errors.raise_error(errors.ERR_INSTRUCTOR_NOT_FOUND, f"Instructor {id} not found")
    return success_object(_instructor_to_json(instructor))


# --- Instructor Approvals ---

@bp.route("/instructors/<instructor_id>/approvals", methods=["POST"])
@require_roles("Registrar")
def create_instructor_approval(instructor_id):
    instructor = db.instructors.get(instructor_id)
    if not instructor:
        errors.raise_error(errors.ERR_INSTRUCTOR_NOT_FOUND, f"Instructor {instructor_id} not found")

    body = get_json_body(required_fields=["state_code"])
    auth = request.auth

    # Singleton check
    for a in db.instructor_approvals.values():
        if a["instructor_id"] == instructor_id and a["state_code"] == body["state_code"]:
            errors.raise_error(errors.ERR_APPROVAL_ALREADY_EXISTS,
                               "Approval already exists for instructor+state")

    approval = db.new_entity({
        "instructor_id": instructor_id,
        "state_code": body["state_code"],
        "application_round": 1,
        "status": "PENDING",
        "valid_from": None,
        "valid_until": None,
        "decided_at": None,
    })
    db.instructor_approvals[approval["id"]] = approval
    db.audit("InstructorApproval", approval["id"], "APPROVAL_SUBMITTED",
             auth["role"], auth["user_id"])
    return success_object(_approval_to_json(approval), 201)


@bp.route("/instructors/<instructor_id>/approvals", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_instructor_approvals(instructor_id):
    instructor = db.instructors.get(instructor_id)
    if not instructor:
        errors.raise_error(errors.ERR_INSTRUCTOR_NOT_FOUND, f"Instructor {instructor_id} not found")
    limit, offset = parse_pagination()
    items = [a for a in db.instructor_approvals.values() if a["instructor_id"] == instructor_id]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_approval_to_json(a) for a in page], limit, offset, total)


@bp.route("/instructor-approvals/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def get_instructor_approval(id):
    approval = db.instructor_approvals.get(id)
    if not approval:
        errors.raise_error(errors.ERR_INSTRUCTOR_APPROVAL_NOT_FOUND,
                           f"InstructorApproval {id} not found")
    return success_object(_approval_to_json(approval))


@bp.route("/instructor-approvals/<id>/decide", methods=["POST"])
@require_roles("StateCommission")
def decide_instructor_approval(id):
    approval = db.instructor_approvals.get(id)
    if not approval:
        errors.raise_error(errors.ERR_INSTRUCTOR_APPROVAL_NOT_FOUND,
                           f"InstructorApproval {id} not found")

    body = get_json_body(
        required_fields=["decision"],
        optional_fields=["valid_from", "valid_until"],
    )
    auth = request.auth

    if approval["status"] not in ("PENDING", "RENEWAL_PENDING"):
        errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                           f"Status is {approval['status']}")

    decision = body["decision"]
    if decision not in ("APPROVED", "DENIED"):
        errors.raise_error(errors.ERR_INVALID_ENUM, f"Invalid decision: {decision}")

    if decision == "APPROVED":
        valid_from_str = body.get("valid_from")
        valid_until_str = body.get("valid_until")
        if not valid_from_str or not valid_until_str:
            errors.raise_error(errors.ERR_INVALID_VALIDITY_WINDOW,
                               "valid_from and valid_until required")
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
        db.audit("InstructorApproval", approval["id"], "STATUS_CHANGE",
                 auth["role"], auth["user_id"],
                 {"from_status": old_status, "to_status": "APPROVED"})
    else:
        old_status = approval["status"]
        is_renewal = old_status == "RENEWAL_PENDING"

        if is_renewal:
            approval["status"] = "EXPIRED"
        else:
            approval["status"] = "DENIED"
        approval["decided_at"] = db.now_iso()
        db.touch(approval)
        db.audit("InstructorApproval", approval["id"], "STATUS_CHANGE",
                 auth["role"], auth["user_id"],
                 {"from_status": old_status, "to_status": approval["status"]})

    return success_object(_approval_to_json(approval))


@bp.route("/instructor-approvals/<id>/resubmit", methods=["POST"])
@require_roles("Registrar")
def resubmit_instructor_approval(id):
    approval = db.instructor_approvals.get(id)
    if not approval:
        errors.raise_error(errors.ERR_INSTRUCTOR_APPROVAL_NOT_FOUND,
                           f"InstructorApproval {id} not found")
    auth = request.auth

    if approval["status"] != "DENIED":
        errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                           f"Status is {approval['status']}, expected DENIED")

    approval["status"] = "PENDING"
    approval["application_round"] += 1
    approval["decided_at"] = None
    db.touch(approval)
    db.audit("InstructorApproval", approval["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "DENIED", "to_status": "PENDING"})
    return success_object(_approval_to_json(approval))


@bp.route("/instructor-approvals/<id>/renew", methods=["POST"])
@require_roles("Registrar")
def renew_instructor_approval(id):
    approval = db.instructor_approvals.get(id)
    if not approval:
        errors.raise_error(errors.ERR_INSTRUCTOR_APPROVAL_NOT_FOUND,
                           f"InstructorApproval {id} not found")
    auth = request.auth

    if approval["status"] == "EXPIRING":
        pass
    elif approval["status"] == "EXPIRED":
        from services.calculations import _extract_date
        valid_until = _extract_date(approval.get("valid_until"))
        if valid_until is None:
            errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID, "No valid_until")
        today = db.today()
        if today > valid_until + timedelta(days=30):
            errors.raise_error(errors.ERR_APPROVAL_RENEWAL_WINDOW_CLOSED,
                               "Late renewal window closed")
    else:
        errors.raise_error(errors.ERR_APPROVAL_STATE_INVALID,
                           f"Status is {approval['status']}, expected EXPIRING or EXPIRED")

    old_status = approval["status"]
    approval["status"] = "RENEWAL_PENDING"
    db.touch(approval)
    db.audit("InstructorApproval", approval["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": "RENEWAL_PENDING"})
    return success_object(_approval_to_json(approval))
