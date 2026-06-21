"""Member registration, wallet top-up, and lifecycle (suspend/reinstate/close)."""
from flask import Blueprint

from db import db, LOCK
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, sorted_by_creation, paginate,
    require_fields, as_int,
)

bp = Blueprint("members", __name__)


def _public_member(m):
    return public(m)


@bp.post("/members/register")
def register_member():
    # Only endpoint reachable without auth headers, but if headers are present
    # the role must be Anonymous-capable. PRD: an Anonymous caller self-registers.
    body = get_json_body()
    require_fields(body, ["business_name", "email"])
    business_name = body["business_name"]
    email = body["email"]
    if not isinstance(business_name, str) or not business_name:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(email, str) or not email:
        raise ApiError("ERR_INVALID_REQUEST")
    plan_tier = body.get("plan_tier", "STANDARD")
    if plan_tier not in ("STANDARD", "PREMIUM"):
        raise ApiError("ERR_INVALID_REQUEST")

    with LOCK:
        member = {
            "business_name": business_name,
            "email": email,
            "plan_tier": plan_tier,
            "status": "ACTIVE",
            "wallet_balance_cents": 0,
            "lifetime_loaded_cents": 0,
            "lifetime_charged_cents": 0,
        }
        stamp_new(member)
        db.members[member["id"]] = member
        return success(_public_member(member), 201)


@bp.get("/members")
def list_members():
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    limit, offset = parse_pagination()
    from flask import request
    status = request.args.get("status")
    with LOCK:
        records = sorted_by_creation(list(db.members.values()))
        if status:
            records = [m for m in records if m["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>")
def get_member(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        member = find_member(member_id)
        return success(_public_member(member))


@bp.post("/members/<member_id>/wallet/top-ups")
def top_up_wallet(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        require_fields(body, ["amount_cents"])
        amount = as_int(body["amount_cents"])
        if amount < 0:
            raise ApiError("ERR_INVALID_REQUEST")
        member["wallet_balance_cents"] += amount
        member["lifetime_loaded_cents"] += amount
        touch(member)
        return success(_public_member(member), 201)


def _lifecycle(member_id, expected_state, target_state, check_obligations=False,
               require_version=True):
    user_id, role = get_identity()
    require_roles(role, {"FacilityManager"})
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        # OCC for suspend/reinstate/close: PRD 3.1 — suspend carries
        # expected_member_version. We treat the version field as guarded where
        # present; a mismatch is ERR_STALE_VERSION. (Body well-formedness first.)
        if require_version and "expected_member_version" in body:
            if body["expected_member_version"] != member["version"]:
                raise ApiError("ERR_STALE_VERSION")
        if member["status"] != expected_state:
            raise ApiError("ERR_INVALID_STATE")
        if check_obligations:
            _ensure_no_open_obligations(member_id)
        member["status"] = target_state
        touch(member)
        return success(_public_member(member))


def _ensure_no_open_obligations(member_id):
    for a in db.storage_assignments.values():
        if a["member_id"] == member_id and a["status"] == "ACTIVE":
            raise ApiError("ERR_MEMBER_HAS_OPEN_OBLIGATIONS")
    for b in db.bookings.values():
        if b["member_id"] == member_id and b["status"] == "CONFIRMED":
            raise ApiError("ERR_MEMBER_HAS_OPEN_OBLIGATIONS")


@bp.post("/members/<member_id>/suspend")
def suspend_member(member_id):
    return _lifecycle(member_id, "ACTIVE", "SUSPENDED")


@bp.post("/members/<member_id>/reinstate")
def reinstate_member(member_id):
    return _lifecycle(member_id, "SUSPENDED", "ACTIVE")


@bp.post("/members/<member_id>/close")
def close_member(member_id):
    return _lifecycle(member_id, "ACTIVE", "CLOSED", check_obligations=True)
