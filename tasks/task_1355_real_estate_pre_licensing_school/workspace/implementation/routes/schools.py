"""School endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import (
    require_roles, get_json_body, parse_pagination,
    check_director_scope,
)
from response import success_object, success_list
from services.calculations import compute_pass_rate

bp = Blueprint("schools", __name__)


def _school_to_json(s):
    return {k: v for k, v in s.items()}


@bp.route("/schools", methods=["POST"])
@require_roles("SchoolDirector")
def create_school():
    body = get_json_body(
        required_fields=["school_name", "school_code", "home_state_code"],
        optional_fields=["pass_rate_threshold_bps"],
    )
    auth = request.auth

    # Validate pass_rate_threshold_bps range
    threshold = body.get("pass_rate_threshold_bps", 6000)
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "pass_rate_threshold_bps must be an integer")
    if threshold < 0 or threshold > 10000:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "pass_rate_threshold_bps must be 0..10000")

    # Check global uniqueness of school_code
    for s in db.schools.values():
        if s["school_code"] == body["school_code"]:
            errors.raise_error(errors.ERR_DUPLICATE_SCHOOL_CODE,
                               f"school_code '{body['school_code']}' already exists")

    school = db.new_entity({
        "school_name": body["school_name"],
        "school_code": body["school_code"],
        "home_state_code": body["home_state_code"],
        "pass_rate_threshold_bps": threshold,
        "director_user_id": auth["user_id"],
        "status": "PROVISIONAL",
        "posture": "GOOD_STANDING",
        "last_evaluation_attempt_count": 0,
        "last_evaluation_first_attempt_pass_rate_bps": None,
    })
    db.schools[school["id"]] = school
    db.audit("School", school["id"], "SCHOOL_CREATED", auth["role"], auth["user_id"])
    return success_object(_school_to_json(school), 201)


@bp.route("/schools", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_schools():
    limit, offset = parse_pagination()
    items = list(db.schools.values())

    # Filter by status
    status_filter = request.args.get("status")
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]

    # Director scope: only see own schools
    auth = request.auth
    if auth["role"] == "SchoolDirector":
        items = [s for s in items if s.get("director_user_id") == auth["user_id"]]

    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_school_to_json(s) for s in page], limit, offset, total)


@bp.route("/schools/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def get_school(id):
    school = db.schools.get(id)
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {id} not found")
    auth = request.auth
    check_director_scope(school, auth)
    return success_object(_school_to_json(school))


def _change_school_status(id, from_states, to_state, event_type="STATUS_CHANGE"):
    school = db.schools.get(id)
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {id} not found")
    if school["status"] not in from_states:
        if school["status"] == "REVOKED":
            errors.raise_error(errors.ERR_SCHOOL_TERMINAL,
                               f"School is REVOKED (terminal)")
        errors.raise_error(errors.ERR_SCHOOL_NOT_LICENSED,
                           f"School status is {school['status']}, expected one of {from_states}")
    auth = request.auth
    old_status = school["status"]
    school["status"] = to_state
    db.touch(school)
    db.audit("School", school["id"], event_type, auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": to_state})
    return school


@bp.route("/schools/<id>/license", methods=["POST"])
@require_roles("StateCommission")
def license_school(id):
    school = _change_school_status(id, ["PROVISIONAL"], "LICENSED")
    return success_object(_school_to_json(school))


@bp.route("/schools/<id>/suspend", methods=["POST"])
@require_roles("StateCommission")
def suspend_school(id):
    school = _change_school_status(id, ["LICENSED"], "SUSPENDED")
    return success_object(_school_to_json(school))


@bp.route("/schools/<id>/reinstate", methods=["POST"])
@require_roles("StateCommission")
def reinstate_school(id):
    school = _change_school_status(id, ["SUSPENDED"], "LICENSED")
    return success_object(_school_to_json(school))


@bp.route("/schools/<id>/revoke", methods=["POST"])
@require_roles("StateCommission")
def revoke_school(id):
    school = db.schools.get(id)
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {id} not found")
    if school["status"] not in ("PROVISIONAL", "LICENSED", "SUSPENDED"):
        errors.raise_error(errors.ERR_SCHOOL_TERMINAL, "School is already REVOKED")
    auth = request.auth
    old_status = school["status"]
    school["status"] = "REVOKED"
    db.touch(school)
    db.audit("School", school["id"], "STATUS_CHANGE", auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": "REVOKED"})
    return success_object(_school_to_json(school))


@bp.route("/schools/<id>/pass-rate-summary", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "ComplianceOfficer")
def pass_rate_summary(id):
    school = db.schools.get(id)
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {id} not found")
    auth = request.auth
    check_director_scope(school, auth)

    today = db.today()
    result = compute_pass_rate(id, today)

    from datetime import date
    return success_object({
        "window_start": result["window_start"].isoformat(),
        "window_end": result["window_end"].isoformat(),
        "first_attempt_count": result["first_attempt_count"],
        "first_attempt_pass_rate_bps": result["first_attempt_pass_rate_bps"],
        "all_attempt_count": result["all_attempt_count"],
        "all_attempts_pass_rate_bps": result["all_attempts_pass_rate_bps"],
        "posture": school["posture"],
    })
