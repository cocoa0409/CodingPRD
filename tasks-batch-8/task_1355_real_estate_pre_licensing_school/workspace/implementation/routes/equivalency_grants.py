"""Equivalency grant endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("equivalency_grants", __name__)


def _grant_to_json(g):
    return {k: v for k, v in g.items()}


def _get_grant(grant_id):
    g = db.equivalency_grants.get(grant_id)
    if not g:
        errors.raise_error(errors.ERR_GRANT_NOT_FOUND, f"EquivalencyGrant {grant_id} not found")
    return g


@bp.route("/equivalency-grants", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_equivalency_grant():
    body = get_json_body(
        required_fields=["course_id", "home_state_code", "recognized_state_code",
                         "expected_course_version"],
    )
    auth = request.auth

    # Existence
    course = db.courses.get(body["course_id"])
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course {body['course_id']} not found")

    # Shape: states must differ
    if body["home_state_code"] == body["recognized_state_code"]:
        errors.raise_error(errors.ERR_GRANT_SAME_STATE,
                           "home_state_code must differ from recognized_state_code")

    # OCC check
    expected = body["expected_course_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "expected_course_version must be an integer")
    if expected != course["version"]:
        errors.raise_error(errors.ERR_STALE_COURSE_VERSION,
                           f"Expected version {expected}, current {course['version']}")

    # Referential: source approval must be APPROVED
    source_approved = any(
        a["course_id"] == body["course_id"]
        and a["state_code"] == body["home_state_code"]
        and a["status"] == "APPROVED"
        for a in db.course_approvals.values()
    )
    if not source_approved:
        errors.raise_error(errors.ERR_SOURCE_APPROVAL_NOT_APPROVED,
                           "Course approval in home state is not APPROVED")

    # Supersede existing ACTIVE/SUSPENDED grants for same triple
    for g in db.equivalency_grants.values():
        if (g["course_id"] == body["course_id"]
                and g["home_state_code"] == body["home_state_code"]
                and g["recognized_state_code"] == body["recognized_state_code"]
                and g["status"] in ("ACTIVE", "SUSPENDED")):
            old_status = g["status"]
            g["status"] = "SUPERSEDED"
            db.touch(g)
            db.audit("EquivalencyGrant", g["id"], "STATUS_CHANGE",
                     "system", "system",
                     {"from_status": old_status, "to_status": "SUPERSEDED"})

    grant = db.new_entity({
        "course_id": body["course_id"],
        "home_state_code": body["home_state_code"],
        "recognized_state_code": body["recognized_state_code"],
        "status": "ACTIVE",
    })
    db.equivalency_grants[grant["id"]] = grant

    # Increment course version
    db.touch(course)

    db.audit("EquivalencyGrant", grant["id"], "GRANT_CREATED",
             auth["role"], auth["user_id"])
    return success_object(_grant_to_json(grant), 201)


@bp.route("/equivalency-grants", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "ComplianceOfficer")
def list_equivalency_grants():
    limit, offset = parse_pagination()
    items = list(db.equivalency_grants.values())

    course_id = request.args.get("course_id")
    if course_id:
        items = [g for g in items if g["course_id"] == course_id]

    recognized_state = request.args.get("recognized_state_code")
    if recognized_state:
        items = [g for g in items if g["recognized_state_code"] == recognized_state]

    status_filter = request.args.get("status")
    if status_filter:
        items = [g for g in items if g["status"] == status_filter]

    # Director scope
    auth = request.auth
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        own_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] in own_school_ids}
        items = [g for g in items if g["course_id"] in own_course_ids]

    items.sort(key=lambda g: g["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_grant_to_json(g) for g in page], limit, offset, total)


@bp.route("/equivalency-grants/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "ComplianceOfficer")
def get_equivalency_grant(id):
    grant = _get_grant(id)
    auth = request.auth
    if auth["role"] == "SchoolDirector":
        course = db.courses.get(grant["course_id"])
        if course:
            school = db.schools.get(course["school_id"])
            if school and school.get("director_user_id") != auth["user_id"]:
                errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")
    return success_object(_grant_to_json(grant))


@bp.route("/equivalency-grants/<id>/revoke", methods=["POST"])
@require_roles("StateCommission", "ComplianceOfficer")
def revoke_equivalency_grant(id):
    grant = _get_grant(id)
    auth = request.auth

    if grant["status"] not in ("ACTIVE", "SUSPENDED"):
        errors.raise_error(errors.ERR_GRANT_STATE_INVALID,
                           f"Grant status is {grant['status']}, expected ACTIVE or SUSPENDED")

    old_status = grant["status"]
    grant["status"] = "REVOKED"
    db.touch(grant)
    db.audit("EquivalencyGrant", grant["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": "REVOKED"})
    return success_object(_grant_to_json(grant))
