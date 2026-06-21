"""Cart-side helpers: ownership and state-transition side effects."""
from db import db
from errors import err
from services.common import touch


def check_cart_ownership(cart, user_id, role):
    """Shopper may only act on their own carts (PRD §2.1). MerchantAdmin bypasses."""
    if role == "Shopper" and cart["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Cart does not belong to the acting customer")


def mark_stale(cart):
    """A previously PRICED cart drops to STALE on any line/application change."""
    if cart["pricing_status"] == "PRICED":
        cart["pricing_status"] = "STALE"
    touch(cart)


def applied_apps(cart_id):
    return [
        a
        for a in db.cart_applications.values()
        if a["cart_id"] == cart_id and a["status"] == "APPLIED"
    ]


def reserved_redemptions(cart_id):
    return [
        r
        for r in db.coupon_redemptions.values()
        if r["cart_id"] == cart_id and r["status"] == "RESERVED"
    ]
