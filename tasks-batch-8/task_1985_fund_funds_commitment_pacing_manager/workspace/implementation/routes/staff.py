"""StaffUser directory endpoints (PRD 3.9)."""

from flask import Blueprint, request

from db import STORE, new_entity, public
from errors import raise_err, ERR_NOT_FOUND
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from validate import body, req_str, req_enum

bp = Blueprint("staff", __name__)

STAFF_ROLES = ["ANALYST", "IC_MEMBER", "OPS_ANALYST"]


@bp.route("/fof/staff-users", methods=["POST"])
def create_staff_user():
    _, role = auth_context()
    require_role(role, ["CIO"])
    data = body()
    # Email is deliberately NOT unique: shared emails model one person with
    # two appointments (the SoD check detects the collision).
    u = new_entity(STORE.staff_users, {
        "display_name": req_str(data, "display_name"),
        "staff_role": req_enum(data, "staff_role", STAFF_ROLES),
        "email": req_str(data, "email"),
    }, common=False)
    return ok(public(u), status=201)


@bp.route("/fof/staff-users", methods=["GET"])
def list_staff_users():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(STORE.staff_users.values(),
                         filters={"staff_role": request.args.get("staff_role")})


@bp.route("/fof/staff-users/<uid>", methods=["GET"])
def get_staff_user(uid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    u = STORE.staff_users.get(uid)
    if u is None:
        raise_err(ERR_NOT_FOUND, "staff user id does not exist")
    return ok(public(u))
