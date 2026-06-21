from flask import Blueprint

import db
import validate
import response
from middleware import get_user_context, require_role
from services import lookup, serialize

bp = Blueprint("parties", __name__)

TRUST_TIERS = {"NEW", "VERIFIED", "TRUSTED", "RESTRICTED"}


@bp.post("/sellers")
def create_seller():
    body = validate.get_json_body()
    display_name = validate.require_string(body, "display_name")
    payout_account_ref = validate.require_string(body, "payout_account_ref")
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin", "Seller"))

    seller = {
        "display_name": display_name,
        "payout_account_ref": payout_account_ref,
        "trust_tier": "NEW",
        "escrow_balance_cents": 0,
        "paid_out_balance_cents": 0,
        "open_fraud_flag_count": 0,
    }
    db.stamp_create(seller)
    db.sellers[seller["id"]] = seller
    return response.object_response(serialize.public(seller), 201)


@bp.get("/sellers/<seller_id>")
def get_seller(seller_id):
    user_id, role = get_user_context()
    require_role(role, ("PlatformAdmin", "Seller", "TrustSafety"))
    seller = lookup.get_seller(seller_id)
    if role == "Seller" and user_id != seller["id"]:
        import errors
        from errors import err
        raise err(errors.ERR_FORBIDDEN_ROLE, "Seller may only read own record")
    return response.object_response(serialize.public(seller), 200)


@bp.patch("/sellers/<seller_id>/trust-tier")
def set_trust_tier(seller_id):
    body = validate.get_json_body()
    trust_tier = validate.require_enum(body, "trust_tier", TRUST_TIERS)
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin", "TrustSafety"))
    seller = lookup.get_seller(seller_id)
    seller["trust_tier"] = trust_tier
    db.touch(seller)
    return response.object_response(serialize.public(seller), 200)


@bp.post("/buyers")
def create_buyer():
    body = validate.get_json_body()
    display_name = validate.require_string(body, "display_name")
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin", "Buyer"))

    buyer = {
        "display_name": display_name,
        "wallet_credit_cents": 0,
        "lifetime_orders_count": 0,
    }
    db.stamp_create(buyer)
    db.buyers[buyer["id"]] = buyer
    return response.object_response(serialize.public(buyer), 201)


@bp.get("/buyers/<buyer_id>")
def get_buyer(buyer_id):
    user_id, role = get_user_context()
    require_role(role, ("PlatformAdmin", "Buyer", "TrustSafety"))
    buyer = lookup.get_buyer(buyer_id)
    if role == "Buyer" and user_id != buyer["id"]:
        import errors
        from errors import err
        raise err(errors.ERR_FORBIDDEN_ROLE, "Buyer may only read own record")
    return response.object_response(serialize.public(buyer), 200)
