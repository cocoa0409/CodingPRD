"""EnrollmentUser provisioning (PRD §3.1)."""
from flask import Blueprint, request

import store
from auth import (
    ALL_ROLES,
    authenticate,
    authorize,
    check_list_enrollment_param,
    check_ownership,
    scope_list,
)
from errors import ERR_ENROLLMENT_NOT_ACTIVE, raise_err
from services import USER_ROLES, guard_enrollment_mutable, user_out
from util import body_json, get_or_404, list_response, new_record, req_enum, req_str, success_object

bp = Blueprint("enrollment_users", __name__)


@bp.route("/treasury/enrollment-users", methods=["POST"])
def create_user():
    _, role, user = authenticate()
    authorize(role, user, ["BankTreasuryManager", "CustomerAdmin"])
    body = body_json()
    enrollment_id = req_str(body, "enrollment_id")
    display_name = req_str(body, "display_name")
    user_role = req_enum(body, "user_role", USER_ROLES)
    enr = get_or_404(store.enrollments, enrollment_id, "TreasuryEnrollment")
    # CustomerAdmin may create users only inside their own enrollment
    check_ownership(user, enr["id"])
    guard_enrollment_mutable(enr)
    if user is not None and enr["status"] != "ACTIVE":
        raise_err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE")
    rec = new_record()
    rec.update({
        "enrollment_id": enr["id"],
        "display_name": display_name,
        "user_role": user_role,
    })
    store.users[rec["id"]] = rec
    return success_object(user_out(rec), 201)


@bp.route("/treasury/enrollment-users/<uid>", methods=["GET"])
def get_user(uid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.users, uid, "EnrollmentUser")
    check_ownership(user, rec["enrollment_id"])
    return success_object(user_out(rec), 200)


@bp.route("/treasury/enrollment-users", methods=["GET"])
def list_users():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.users.values(), user, lambda u: u["enrollment_id"])
    if enr_filter is not None:
        records = [u for u in records if u["enrollment_id"] == enr_filter]
    role_filter = request.args.get("user_role")
    if role_filter is not None:
        records = [u for u in records if u["user_role"] == role_filter]
    return list_response(records, user_out)
