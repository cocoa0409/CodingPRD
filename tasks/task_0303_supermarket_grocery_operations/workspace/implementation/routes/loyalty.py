"""Loyalty members, clipping, clipped coupons."""
from flask import Blueprint, request, g

from auth import require_role, unauthorized
from common import (
    stamp_new, touch, require_dict, get_str, pagination_params, paginate,
)
from clock import clock
from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
    ERR_MEMBER_NOT_ACTIVE, ERR_MEMBER_NOT_SUSPENDED, ERR_MEMBER_NOT_CLOSEABLE,
)
from lookup import get_member, get_coupon, get_clip
from response import success, list_response
from serializers import ser_member, ser_clip

bp = Blueprint("loyalty", __name__)


def recompute_tier(member):
    spend = member["lifetime_spend_cents"]
    if spend >= 200000:
        member["tier"] = "GOLD"
    elif spend >= 50000:
        member["tier"] = "SILVER"
    else:
        member["tier"] = "BASIC"


# ---------------- Members ----------------

@bp.route("/members", methods=["POST"])
def create_member():
    require_role("StoreManager", "Cashier")
    body = require_dict(request.get_json(silent=True))
    email = get_str(body, "email")
    full_name = get_str(body, "full_name")
    for m in db.members.values():
        if m["email"] == email:
            raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "email already exists")
    rec = stamp_new({
        "email": email,
        "full_name": full_name,
        "points_balance": 0,
        "tier": "BASIC",
        "lifetime_spend_cents": 0,
        "status": "ACTIVE",
    })
    db.members[rec["id"]] = rec
    return success(ser_member(rec), status=201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member_route(mid):
    require_role("StoreManager", "Cashier", "LoyaltyMember")
    # entity-backed ownership: a LoyaltyMember may read only its own record
    if g.role == "LoyaltyMember" and g.user_id != mid:
        unauthorized()
    m = get_member(mid)
    return success(ser_member(m))


@bp.route("/members/<mid>/suspend", methods=["POST"])
def suspend_member(mid):
    require_role("StoreManager")
    m = get_member(mid)
    if m["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE[0], ERR_MEMBER_NOT_ACTIVE[1], "member not active")
    m["status"] = "SUSPENDED"
    touch(m)
    return success(ser_member(m))


@bp.route("/members/<mid>/reactivate", methods=["POST"])
def reactivate_member(mid):
    require_role("StoreManager")
    m = get_member(mid)
    if m["status"] != "SUSPENDED":
        raise ApiError(ERR_MEMBER_NOT_SUSPENDED[0], ERR_MEMBER_NOT_SUSPENDED[1], "member not suspended")
    m["status"] = "ACTIVE"
    touch(m)
    return success(ser_member(m))


@bp.route("/members/<mid>/close", methods=["POST"])
def close_member(mid):
    require_role("StoreManager")
    m = get_member(mid)
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_MEMBER_NOT_CLOSEABLE[0], ERR_MEMBER_NOT_CLOSEABLE[1], "member not closeable")
    m["status"] = "CLOSED"
    touch(m)
    # cascade: member's CLIPPED coupons -> EXPIRED
    for cc in db.clipped_coupons.values():
        if cc["member_id"] == mid and cc["status"] == "CLIPPED":
            cc["status"] = "EXPIRED"
            touch(cc)
    return success(ser_member(m))


@bp.route("/members/<mid>/clip", methods=["POST"])
def clip_coupon(mid):
    require_role("LoyaltyMember", "Cashier", "StoreManager")
    # entity-backed ownership: a LoyaltyMember clips only onto its own account
    if g.role == "LoyaltyMember" and g.user_id != mid:
        unauthorized()
    m = get_member(mid)
    body = require_dict(request.get_json(silent=True))
    coupon_id = body.get("coupon_id")
    if not isinstance(coupon_id, str) or not coupon_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "coupon_id is required")
    get_coupon(coupon_id)
    # duplicate live clip: same coupon while a prior clip is still CLIPPED
    for cc in db.clipped_coupons.values():
        if cc["member_id"] == mid and cc["coupon_id"] == coupon_id and cc["status"] == "CLIPPED":
            raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "coupon already clipped")
    rec = stamp_new({
        "member_id": mid,
        "coupon_id": coupon_id,
        "redeemed_in_sale_id": None,
        "status": "CLIPPED",
    })
    db.clipped_coupons[rec["id"]] = rec
    return success(ser_clip(rec), status=201)


@bp.route("/members/<mid>/clipped-coupons", methods=["GET"])
def list_member_clips(mid):
    require_role("LoyaltyMember", "Cashier", "StoreManager")
    if g.role == "LoyaltyMember" and g.user_id != mid:
        unauthorized()
    get_member(mid)
    limit, offset = pagination_params(request.args)
    items = [cc for cc in db.clipped_coupons.values() if cc["member_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [cc for cc in items if cc["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_clip(cc) for cc in page], limit, offset, total)


@bp.route("/clipped-coupons/<cid>", methods=["GET"])
def get_clip_route(cid):
    require_role("LoyaltyMember", "Cashier", "StoreManager")
    cc = get_clip(cid)
    # entity-backed ownership against the clip's member FK
    if g.role == "LoyaltyMember" and g.user_id != cc["member_id"]:
        unauthorized()
    return success(ser_clip(cc))
