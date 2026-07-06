"""Loyalty challenges."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (body, require_fields, require_str, require_int,
                     get_or_404, fk_or_404, paginate, filter_by)
from middleware import get_auth, require_roles, require_owner
from response import success
from serializers import serialize

bp = Blueprint("challenges", __name__)


@bp.post("/loyalty-challenges")
def create_challenge():
    user_id, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer"})
    data = body()
    require_fields(data, ["customer_id", "target_order_count", "bonus_points"])
    require_str(data, "customer_id")
    require_int(data, "target_order_count")
    require_int(data, "bonus_points")
    # Customer may only enroll self; admin may act for anyone
    require_owner(role, user_id, data["customer_id"])
    fk_or_404("customer", data["customer_id"])
    if data["target_order_count"] < 1:
        raise err("ERR_INVALID_REQUEST", "target_order_count must be >= 1.")
    if data["bonus_points"] < 1:
        raise err("ERR_INVALID_REQUEST", "bonus_points must be >= 1.")

    ch = db.common_fields()
    ch.update({
        "customer_id": data["customer_id"],
        "target_order_count": data["target_order_count"],
        "bonus_points": data["bonus_points"],
        "progress_count": 0,
        "rounds_completed": 0,
        "status": "IN_PROGRESS",
    })
    db.loyalty_challenges[ch["id"]] = ch
    return success(serialize("loyalty_challenge", ch), 201)


@bp.get("/loyalty-challenges/<cid>")
def get_challenge(cid):
    get_auth()
    ch = get_or_404("loyalty_challenge", cid)
    return success(serialize("loyalty_challenge", ch), 200)


@bp.get("/loyalty-challenges")
def list_challenges():
    get_auth()
    customer_id = request.args.get("customer_id")
    items = filter_by(db.loyalty_challenges, customer_id=customer_id)
    page, meta = paginate(items)
    return success([serialize("loyalty_challenge", c) for c in page], 200, meta)


@bp.post("/loyalty-challenges/<cid>/start-round")
def start_round(cid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    ch = get_or_404("loyalty_challenge", cid)
    require_owner(role, user_id, ch["customer_id"])
    if ch["status"] != "ROUND_COMPLETE":
        raise err("ERR_CHALLENGE_NOT_READY", "Challenge is not in ROUND_COMPLETE.")
    ch["status"] = "IN_PROGRESS"
    ch["progress_count"] = 0
    db.touch(ch)
    return success(serialize("loyalty_challenge", ch), 200)


@bp.post("/loyalty-challenges/<cid>/expire")
def expire_challenge(cid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    ch = get_or_404("loyalty_challenge", cid)
    if ch["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only IN_PROGRESS challenges may expire.")
    ch["status"] = "EXPIRED"
    db.touch(ch)
    return success(serialize("loyalty_challenge", ch), 200)
