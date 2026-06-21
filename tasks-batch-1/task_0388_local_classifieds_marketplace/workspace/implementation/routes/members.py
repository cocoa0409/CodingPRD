"""Member endpoints (PRD §3.1)."""
import random
import string

from flask import Blueprint, request

import constants as C
from db import store
from domain import recompute_trust_score, touch, cascade_suspend, cascade_ban
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import member_out, flag_out
import validate as V

bp = Blueprint("members", __name__)


def _find_member(member_id):
    m = store.members.get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found.")
    return m


@bp.route("/members", methods=["POST"])
def create_member():
    # Registration is open to Anonymous callers (§3.1). Auth headers optional.
    auth_context(require_auth=False)
    body = get_json_body()

    email = V.require_str(body, "email")
    display_name = V.require_str(body, "display_name")
    role_kind = V.require_enum(body, "role_kind", C.ROLE_KIND_VALUES, default="BOTH")

    # email unique across all members (§3.1).
    for m in store.members.values():
        if m["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already in use.")

    mid = store.new_id()
    now = store.now()
    rec = {
        "id": mid,
        "email": email,
        "display_name": display_name,
        "role_kind": role_kind,
        "status": "ACTIVE",
        "phone_verified": False,
        "verification_code": None,
        "trust_score": C.BASE_TRUST,
        "upheld_flag_count": 0,
        "active_listing_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.members[mid] = rec
    return object_response(member_out(rec), 201)


@bp.route("/members", methods=["GET"])
def list_members():
    auth_context(require_auth=False)
    limit, offset = parse_pagination(request.args)
    email = request.args.get("email")
    status = request.args.get("status")
    recs = list(store.members.values())
    if email is not None:
        recs = [m for m in recs if m["email"] == email]
    if status is not None:
        recs = [m for m in recs if m["status"] == status]
    return paginate_and_respond(recs, limit, offset, member_out)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    auth_context(require_auth=False)
    m = _find_member(member_id)
    return object_response(member_out(m))


@bp.route("/members/<member_id>/request-verification", methods=["POST"])
def request_verification(member_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER})
    m = _find_member(member_id)
    # Mint a server-issued one-time code, store it, and return it (§3.1).
    code = "".join(random.choices(string.digits, k=6))
    m["verification_code"] = code
    return object_response(member_out(m))


@bp.route("/members/<member_id>/confirm-verification", methods=["POST"])
def confirm_verification(member_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER})
    m = _find_member(member_id)
    body = get_json_body()
    submitted = V.require_str(body, "verification_code")
    if m["verification_code"] is None or submitted != m["verification_code"]:
        raise err("ERR_VERIFICATION_CODE_MISMATCH", "Verification code does not match.")
    m["phone_verified"] = True
    m["verification_code"] = None
    recompute_trust_score(m)
    touch(m)
    return object_response(member_out(m))


@bp.route("/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR})
    m = _find_member(member_id)
    # Permitted only while ACTIVE (§3.1).
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Member is not ACTIVE.")
    m["status"] = "SUSPENDED"
    cascade_suspend(m)
    touch(m)
    return object_response(member_out(m))


@bp.route("/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR})
    m = _find_member(member_id)
    if m["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Member is not SUSPENDED.")
    m["status"] = "ACTIVE"
    # Listings are NOT automatically republished (§3.1).
    touch(m)
    return object_response(member_out(m))


@bp.route("/members/<member_id>/ban", methods=["POST"])
def ban_member(member_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR})
    m = _find_member(member_id)
    # Permitted from ACTIVE or SUSPENDED (§3.1).
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Member cannot be banned from current state.")
    # Only when upheld_flag_count >= BAN_UPHELD_THRESHOLD (§3.1).
    if m["upheld_flag_count"] < C.BAN_UPHELD_THRESHOLD:
        raise err("ERR_BAN_THRESHOLD_NOT_MET", "Upheld flag count below ban threshold.")
    m["status"] = "BANNED"
    cascade_ban(m)
    touch(m)
    return object_response(member_out(m))


@bp.route("/members/<member_id>/flags", methods=["GET"])
def list_member_flags(member_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_member(member_id)
    limit, offset = parse_pagination(request.args)
    recs = [
        f for f in store.flags.values()
        if f["target_type"] == "MEMBER" and f["target_member_id"] == member_id
    ]
    status = request.args.get("status")
    if status is not None:
        recs = [f for f in recs if f["status"] == status]
    return paginate_and_respond(recs, limit, offset, flag_out)
