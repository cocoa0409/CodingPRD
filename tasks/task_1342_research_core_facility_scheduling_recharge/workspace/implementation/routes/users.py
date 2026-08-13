"""Users (PRD §3.1)."""

from flask import Blueprint, request

from auth import authenticate, require_roles, is_entity_role, check_resource_ownership, auth_id
from errors import fail
from helpers import Body, validate_body, non_empty_str, email_ok, system_cancel, system_reject
from store import store
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts
from store import now

bp = Blueprint("users", __name__)


def _get_user_or_404(uid):
    u = store.users.get(uid)
    if u is None:
        fail("ERR_NOT_FOUND", "User not found")
    return u


@bp.route("/users", methods=["POST"])
def create_user():
    authenticate()
    require_roles("FacilityAdmin")
    body = Body(request.get_json(silent=True))
    # Priority 21 — field formats
    validate_body(
        body,
        allowed={"full_name", "email", "affiliation", "department", "is_pi"},
        required={"full_name", "email", "affiliation"},
        checkers={
            "full_name": non_empty_str,
            "email": email_ok,
            "affiliation": lambda v: v in ("INTERNAL", "EXTERNAL"),
            "department": lambda v: isinstance(v, str),
            "is_pi": lambda v: isinstance(v, bool),
        },
    )
    # Priority 22 — uniqueness of email
    for u in store.users.values():
        if u["email"] == body.get("email"):
            fail("ERR_UNIQUE_CONSTRAINT", "A user with this email already exists")
    user = new_entity({
        "full_name": body.get("full_name"),
        "email": body.get("email"),
        "affiliation": body.get("affiliation"),
        "department": body.get("department"),
        "is_pi": bool(body.get("is_pi", False)),
        "status": "ACTIVE",
    })
    store.users[user["id"]] = user
    from helpers import ser_user
    return ok_object(ser_user(user), status=201)


@bp.route("/users", methods=["GET"])
def list_users():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer")
    from helpers import ser_user
    limit, offset = parse_pagination(request.args)
    items = list(store.users.values())
    affiliation = request.args.get("affiliation")
    if affiliation is not None:
        items = [u for u in items if u["affiliation"] == affiliation]
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_user)


@bp.route("/users/<uid>", methods=["GET"])
def get_user(uid):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    user = _get_user_or_404(uid)
    check_resource_ownership(user["id"])
    from helpers import ser_user
    return ok_object(ser_user(user))


@bp.route("/users/<uid>/suspend", methods=["POST"])
def suspend_user(uid):
    authenticate()
    require_roles("FacilityAdmin")
    user = _get_user_or_404(uid)
    if user["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE user can be suspended")
    user["status"] = "SUSPENDED"
    touch(user)
    # Cascade: future REQUESTED -> REJECTED; future APPROVED -> CANCELLED (waived)
    for b in list(store.bookings.values()):
        if b["user_id"] != uid:
            continue
        if b["status"] == "REQUESTED" and b["_start_at"] > now():
            system_reject(b)
        elif b["status"] == "APPROVED" and b["_start_at"] > now():
            system_cancel(b, "USER_SUSPENDED")
    from helpers import ser_user
    return ok_object(ser_user(user))


@bp.route("/users/<uid>/reactivate", methods=["POST"])
def reactivate_user(uid):
    authenticate()
    require_roles("FacilityAdmin")
    user = _get_user_or_404(uid)
    if user["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Only a SUSPENDED user can be reactivated")
    user["status"] = "ACTIVE"
    touch(user)
    from helpers import ser_user
    return ok_object(ser_user(user))
