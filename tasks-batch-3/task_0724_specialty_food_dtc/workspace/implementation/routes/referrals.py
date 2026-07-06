from flask import Blueprint, request

from db import db, new_common, public, touch
from middleware import auth, require_role
from errors import (
    err,
    ERR_SELF_REFERRAL,
    ERR_INVALID_STATE,
)
from helpers import (
    body,
    require_str,
    find_customer,
    find_referral,
    paginate,
    sorted_by_created,
)
from response import ok_object, ok_list
from services import calc

bp = Blueprint("referrals", __name__)


def serialize_referral(r):
    return public(r)


@bp.post("/referrals")
def create_referral():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    referrer_id = require_str(data, "referrer_id")
    referred_id = require_str(data, "referred_id")
    # existence left-to-right (priority 4)
    find_customer(referrer_id)
    find_customer(referred_id)
    # self-referral (priority 14)
    if referrer_id == referred_id:
        raise err(ERR_SELF_REFERRAL, "Cannot refer self")

    rid = db.new_id()
    ref = {
        "id": rid,
        "referrer_id": referrer_id,
        "referred_id": referred_id,
        "status": "PENDING",
        "reward_points": 0,
    }
    ref.update(new_common())
    db.referrals[rid] = ref
    return ok_object(serialize_referral(ref), 201)


@bp.get("/referrals")
def list_referrals():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    items = list(db.referrals.values())
    for key in ("referrer_id", "referred_id"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_referral(r) for r in page], limit, offset, total)


@bp.get("/referrals/<rid>")
def get_referral(rid):
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    return ok_object(serialize_referral(find_referral(rid)))


@bp.post("/referrals/<rid>/reward")
def reward_referral(rid):
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    ref = find_referral(rid)
    if ref["status"] != "QUALIFIED":
        raise err(ERR_INVALID_STATE, "Reward requires QUALIFIED")
    ref["reward_points"] = calc.REFERRAL_REWARD_POINTS
    touch(ref)
    referrer = db.customers.get(ref["referrer_id"])
    if referrer is not None:
        referrer["loyalty_points_balance"] += calc.REFERRAL_REWARD_POINTS
        touch(referrer)
    return ok_object(serialize_referral(ref))


@bp.post("/referrals/<rid>/void")
def void_referral(rid):
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    ref = find_referral(rid)
    if ref["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Void requires PENDING")
    ref["status"] = "VOID"
    touch(ref)
    return ok_object(serialize_referral(ref))
