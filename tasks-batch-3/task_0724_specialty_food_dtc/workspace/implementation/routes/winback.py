from flask import Blueprint, request

from db import db, new_common, public, touch
from clock import clock, parse_iso
from middleware import auth, require_role
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_DUE,
    ERR_NOT_WINBACK_ELIGIBLE,
    ERR_VALIDATION,
)
from helpers import (
    body,
    require_str,
    find_customer,
    find_winback,
    paginate,
    sorted_by_created,
)
from response import ok_object, ok_list
from services import domain

bp = Blueprint("winback", __name__)


def serialize_offer(o):
    return public(o)


@bp.post("/winback-offers")
def create_offer():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    customer_id = require_str(data, "customer_id")
    if "discount_pct" not in data or data["discount_pct"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing discount_pct")
    discount_pct = data["discount_pct"]
    if isinstance(discount_pct, bool) or not isinstance(discount_pct, (int, float)):
        raise err(ERR_INVALID_REQUEST, "discount_pct must be a number")
    expires_iso = require_str(data, "expires_iso")
    if parse_iso(expires_iso) is None:
        raise err(ERR_INVALID_REQUEST, "Invalid expires_iso")
    cust = find_customer(customer_id)
    # semantic range (priority generic ERR_VALIDATION)
    if not (0.05 <= discount_pct <= 0.50):
        raise err(ERR_VALIDATION, "discount_pct out of range")
    # eligibility (priority 13)
    if not (cust["status"] == "DORMANT" and cust["churn_band"] == "CHURN_IMMINENT"):
        raise err(ERR_NOT_WINBACK_ELIGIBLE, "Customer not win-back eligible")

    oid = db.new_id()
    offer = {
        "id": oid,
        "customer_id": customer_id,
        "discount_pct": discount_pct,
        "expires_iso": expires_iso,
        "status": "OFFERED",
    }
    offer.update(new_common())
    db.winback_offers[oid] = offer
    domain.update_winback_eligible(cust)
    touch(cust)
    return ok_object(serialize_offer(offer), 201)


@bp.get("/winback-offers/<oid>")
def get_offer(oid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    offer = find_winback(oid)
    if role == "Customer" and user_id != offer["customer_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return ok_object(serialize_offer(offer))


@bp.get("/winback-offers")
def list_offers():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    items = list(db.winback_offers.values())
    v = request.args.get("customer_id")
    if v is not None:
        items = [o for o in items if o["customer_id"] == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_offer(o) for o in page], limit, offset, total)


@bp.post("/winback-offers/<oid>/redeem")
def redeem_offer(oid):
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    offer = find_winback(oid)
    if role == "Customer" and user_id != offer["customer_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    if offer["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Redeem requires OFFERED")
    exp = parse_iso(offer["expires_iso"])
    if clock.now() >= exp:
        raise err(ERR_NOT_DUE, "Offer expired")
    offer["status"] = "REDEEMED"
    touch(offer)
    cust = db.customers.get(offer["customer_id"])
    if cust is not None:
        domain.update_winback_eligible(cust)
        touch(cust)
    return ok_object(serialize_offer(offer))
