"""Flag / moderation endpoints (PRD §3.7)."""
from flask import Blueprint, request

import constants as C
from db import store
from domain import touch, recompute_trust_score, remove_listing
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import flag_out
import validate as V

bp = Blueprint("flags", __name__)


def _find_flag(flag_id):
    f = store.flags.get(flag_id)
    if f is None:
        raise err("ERR_NOT_FOUND", "Flag not found.")
    return f


@bp.route("/flags", methods=["POST"])
def create_flag():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER})
    body = get_json_body()

    reporter_id = V.require_str(body, "reporter_id")
    target_type = V.require_enum(body, "target_type", C.FLAG_TARGET_TYPE_VALUES)
    reason = V.require_enum(body, "reason", C.FLAG_REASON_VALUES)
    target_listing_id = V.optional_str(body, "target_listing_id", default=None, allow_empty=False)
    target_member_id = V.optional_str(body, "target_member_id", default=None, allow_empty=False)

    # Existence (§2.5): reporter, then the polymorphic target.
    reporter = store.members.get(reporter_id)
    if reporter is None:
        raise err("ERR_NOT_FOUND", "Reporter not found.")

    target_listing = None
    target_member = None
    if target_type == "LISTING":
        if not target_listing_id:
            raise err("ERR_INVALID_REQUEST", "target_listing_id required for LISTING target.")
        target_listing = store.listings.get(target_listing_id)
        if target_listing is None:
            raise err("ERR_NOT_FOUND", "Target listing not found.")
    else:  # MEMBER
        if not target_member_id:
            raise err("ERR_INVALID_REQUEST", "target_member_id required for MEMBER target.")
        target_member = store.members.get(target_member_id)
        if target_member is None:
            raise err("ERR_NOT_FOUND", "Target member not found.")

    now = store.now()
    fid = store.new_id()
    rec = {
        "id": fid,
        "reporter_id": reporter_id,
        "target_type": target_type,
        "target_listing_id": target_listing_id if target_type == "LISTING" else None,
        "target_member_id": target_member_id if target_type == "MEMBER" else None,
        "reason": reason,
        "status": "OPEN",
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.flags[fid] = rec

    # Listing flag: increment active_flag_count; auto-hide at SPAM_FLAG_THRESHOLD (§3.7).
    if target_type == "LISTING":
        target_listing["active_flag_count"] += 1
        touch(target_listing)
        if (
            target_listing["active_flag_count"] >= C.SPAM_FLAG_THRESHOLD
            and target_listing["publication_status"] in ("DRAFT", "ACTIVE", "EXPIRED")
        ):
            remove_listing(target_listing)

    return object_response(flag_out(rec), 201)


@bp.route("/flags", methods=["GET"])
def list_flags():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    limit, offset = parse_pagination(request.args)
    recs = list(store.flags.values())
    for key in ("status", "target_type", "target_member_id", "reporter_id"):
        if key in request.args:
            val = request.args.get(key)
            recs = [f for f in recs if f[key] == val]
    return paginate_and_respond(recs, limit, offset, flag_out)


@bp.route("/flags/<flag_id>", methods=["GET"])
def get_flag(flag_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    f = _find_flag(flag_id)
    return object_response(flag_out(f))


@bp.route("/flags/<flag_id>/uphold", methods=["POST"])
def uphold_flag(flag_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR})
    f = _find_flag(flag_id)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Flag is not OPEN.")
    body = get_json_body()
    note = V.optional_str(body, "resolution_note", default=None)

    # Upheld effects (§3.7).
    if f["target_type"] == "LISTING":
        listing = store.listings.get(f["target_listing_id"])
        if listing is not None:
            if listing["active_flag_count"] > 0:
                listing["active_flag_count"] -= 1
            touch(listing)
            seller = store.members.get(listing["seller_id"])
            if seller is not None:
                seller["upheld_flag_count"] += 1
                recompute_trust_score(seller)
                touch(seller)
    else:  # MEMBER
        member = store.members.get(f["target_member_id"])
        if member is not None:
            member["upheld_flag_count"] += 1
            recompute_trust_score(member)
            touch(member)

    f["status"] = "UPHELD"
    if note is not None:
        f["resolution_note"] = note
    touch(f)
    return object_response(flag_out(f))


@bp.route("/flags/<flag_id>/dismiss", methods=["POST"])
def dismiss_flag(flag_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR})
    f = _find_flag(flag_id)
    if f["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Flag is not OPEN.")
    body = get_json_body()
    note = V.optional_str(body, "resolution_note", default=None)

    # Dismissed effects (§3.7): listing flag decrements active_flag_count only.
    if f["target_type"] == "LISTING":
        listing = store.listings.get(f["target_listing_id"])
        if listing is not None:
            if listing["active_flag_count"] > 0:
                listing["active_flag_count"] -= 1
            touch(listing)
    # MEMBER target: no counter changes (§3.7).

    f["status"] = "DISMISSED"
    if note is not None:
        f["resolution_note"] = note
    touch(f)
    return object_response(flag_out(f))
