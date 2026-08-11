"""Shopper endpoints."""

from flask import Blueprint, request

from db import store, stamp, touch
from errors import bad_request, invalid_state
from services import ser_shopper, ser_order, get_or_404
from util import require_roles, respond, body, req_str, paginate
from errors import ApiError

bp = Blueprint("shoppers", __name__)


def _own_shopper(uid, role, shopper_id):
    if role == "Shopper" and uid != shopper_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may act only on its own resources")


@bp.post("/shoppers")
def create_shopper():
    require_roles("Shopper", "PlatformAdmin")
    b = body(required=True)
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    postal_code = req_str(b, "postal_code")
    for s in store["shoppers"].values():
        if s["email"] == email:
            bad_request("email must be unique across shoppers")
    shopper = {
        "email": email,
        "full_name": full_name,
        "postal_code": postal_code,
        "status": "ACTIVE",
        "fraud_strikes": 0,
    }
    stamp(shopper)
    store["shoppers"][shopper["id"]] = shopper
    return respond(ser_shopper(shopper), 201)


@bp.get("/shoppers/<sid>")
def get_shopper(sid):
    uid, role = require_roles("Shopper", "SupportAgent", "PlatformAdmin")
    _own_shopper(uid, role, sid)
    return respond(ser_shopper(get_or_404("shoppers", sid)))


@bp.get("/shoppers/<sid>/return-orders")
def list_shopper_orders(sid):
    uid, role = require_roles("Shopper", "SupportAgent", "PlatformAdmin")
    _own_shopper(uid, role, sid)
    get_or_404("shoppers", sid)
    items = [o for o in store["orders"].values() if o["shopper_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    return respond([ser_order(o) for o in page], page=meta)


@bp.post("/shoppers/<sid>/unrestrict")
def unrestrict_shopper(sid):
    require_roles("SupportAgent", "PlatformAdmin")
    shopper = get_or_404("shoppers", sid)
    if shopper["status"] != "RESTRICTED":
        invalid_state("Only a RESTRICTED shopper can be unrestricted")
    shopper["status"] = "ACTIVE"
    shopper["fraud_strikes"] = 0
    touch(shopper)
    return respond(ser_shopper(shopper))
