"""Member endpoints: register, read, OCC-guarded patch, reinstate, steward flag."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_MEMBER_NOT_FOUND, ERR_NOT_OWNER,
    ERR_MEMBER_NOT_SUSPENDED, ERR_STALE_VERSION,
)
from helpers import get_body, req_string, req_bool, req_int, paginate
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("members", __name__)


def _email_in_use(email, exclude_id=None):
    return any(
        m["email"] == email and m["id"] != exclude_id
        for m in store.members.values()
    )


def _get_member_or_404(member_id):
    member = store.members.get(member_id)
    if member is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, 404, "Member not found")
    return member


@bp.route("/dog-park/members", methods=["POST"])
def register_member():
    require_auth(["Anonymous"])
    body = get_body()
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    phone = body.get("phone", None)
    if phone is not None and not isinstance(phone, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "phone must be a string or null")
    if _email_in_use(email):
        raise ApiError(ERR_INVALID_REQUEST, 400, "email is already registered")
    member = domain.new_entity(store.members, {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "is_steward": False,
        "status": "PENDING_VERIFICATION",
        "strike_points": 0,
    })
    return ok(domain.member_view(member), 201)


@bp.route("/dog-park/members/<memberId>", methods=["GET"])
def get_member(memberId):
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    # Stage 4 ownership: pure path comparison, before existence.
    if role == "Member" and memberId != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Members may only read their own record")
    member = _get_member_or_404(memberId)
    return ok(domain.member_view(member))


@bp.route("/dog-park/members/<memberId>", methods=["PATCH"])
def patch_member(memberId):
    uid, role = require_auth(["Member", "ParkAdmin"])
    if role == "Member" and memberId != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "Members may only update their own record")
    body = get_body()
    expected = req_int(body, "expected_member_version")
    updates = {}
    if "full_name" in body:
        updates["full_name"] = req_string(body, "full_name")
    if "email" in body:
        email = req_string(body, "email")
        if _email_in_use(email, exclude_id=memberId):
            raise ApiError(ERR_INVALID_REQUEST, 400, "email is already registered")
        updates["email"] = email
    if "phone" in body:
        phone = body["phone"]
        if phone is not None and not isinstance(phone, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "phone must be a string or null")
        updates["phone"] = phone
    member = _get_member_or_404(memberId)
    # Stage 7 OCC — before any resource-state rule.
    if expected != member["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_member_version does not match the current version")
    member.update(updates)
    domain.touch(member)
    return ok(domain.member_view(member))


@bp.route("/dog-park/members/<memberId>/reinstate", methods=["POST"])
def reinstate_member(memberId):
    require_auth(["ParkAdmin"])
    member = _get_member_or_404(memberId)
    if member["status"] != "SUSPENDED":
        raise ApiError(ERR_MEMBER_NOT_SUSPENDED, 409,
                       "Reinstate requires a SUSPENDED member")
    member["strike_points"] = 0
    memberships = sorted(
        (ms for ms in store.memberships.values() if ms["member_id"] == memberId),
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    latest = memberships[-1] if memberships else None
    if latest is not None and latest["status"] == "SUSPENDED":
        latest["status"] = "ACTIVE"
        domain.touch(latest)
        member["status"] = "ACTIVE"
    elif latest is not None and latest["status"] == "EXPIRED":
        member["status"] = "LAPSED"
    else:
        member["status"] = "ACTIVE"
    domain.touch(member)
    return ok(domain.member_view(member))


@bp.route("/dog-park/members/<memberId>/steward-status", methods=["POST"])
def set_steward_status(memberId):
    require_auth(["ParkAdmin"])
    body = get_body()
    flag = req_bool(body, "is_steward")
    member = _get_member_or_404(memberId)
    member["is_steward"] = flag
    domain.touch(member)
    return ok(domain.member_view(member))
