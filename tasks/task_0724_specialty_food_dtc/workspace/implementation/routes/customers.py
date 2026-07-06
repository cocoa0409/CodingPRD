from flask import Blueprint, request

from db import db, new_common, public
from clock import clock
from middleware import auth, require_role
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_DUPLICATE_EMAIL,
    ERR_INVALID_STATE,
)
from helpers import (
    body,
    require_str,
    require_enum,
    find_customer,
    find_referral,
    paginate,
    sorted_by_created,
    ZONES,
)
from response import ok_object, ok_list
from services import domain

bp = Blueprint("customers", __name__)


def serialize_customer(c):
    return public(c)


@bp.post("/customers")
def create_customer():
    _, role = auth()
    require_role(role, {"PlatformAdmin", "CorporateBuyer"})
    data = body()
    email = require_str(data, "email")
    full_name = require_str(data, "full_name")
    home_zone = require_str(data, "home_zone")
    require_enum(home_zone, ZONES, "home_zone")
    referrer_id = data.get("referrer_id")
    if referrer_id is not None:
        find_customer(referrer_id)  # existence

    # duplicate email (priority 18)
    for c in db.customers.values():
        if c["email"] == email:
            raise err(ERR_DUPLICATE_EMAIL, "Email already registered")

    cid = db.new_id()
    cust = {
        "id": cid,
        "email": email,
        "full_name": full_name,
        "home_zone": home_zone,
        "status": "ACTIVE",
        "wallet_credit_cents": 0,
        "loyalty_points_balance": 0,
        "lifetime_order_count": 0,
        "lifetime_failed_payment_count": 0,
        "lifetime_skip_count": 0,
        "last_order_at": None,
        "churn_risk_score": 0,
        "churn_band": "OK",
        "winback_eligible": False,
        "_events": [],
    }
    cust.update(new_common())
    db.customers[cid] = cust

    if referrer_id is not None:
        rid = db.new_id()
        ref = {
            "id": rid,
            "referrer_id": referrer_id,
            "referred_id": cid,
            "status": "PENDING",
            "reward_points": 0,
        }
        ref.update(new_common())
        db.referrals[rid] = ref

    return ok_object(serialize_customer(cust), 201)


@bp.get("/customers")
def list_customers():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    items = list(db.customers.values())
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_customer(c) for c in page], limit, offset, total)


@bp.get("/customers/<cid>")
def get_customer(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer", "CorporateBuyer"})
    cust = find_customer(cid)
    if role in ("Customer", "CorporateBuyer") and user_id != cid:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return ok_object(serialize_customer(cust))


@bp.get("/customers/<cid>/risk")
def customer_risk(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    cust = find_customer(cid)
    if role == "Customer" and user_id != cid:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    variant = request.args.get("variant", "ACUTE")
    if variant not in ("ACUTE", "CHRONIC"):
        variant = "ACUTE"
    score, band = domain.compute_churn(cust, variant)
    out = serialize_customer(cust)
    out["churn_risk_score"] = score
    out["churn_band"] = band
    return ok_object(out)


@bp.post("/customers/<cid>/dormancy/mark")
def mark_dormant(cid):
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    cust = find_customer(cid)
    if cust["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Customer not ACTIVE")
    from db import touch
    cust["status"] = "DORMANT"
    touch(cust)
    domain.recompute_customer_churn(cust)
    return ok_object(serialize_customer(cust))


@bp.get("/customers/<cid>/orders")
def customer_orders(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    find_customer(cid)
    if role == "Customer" and user_id != cid:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    from routes.orders import serialize_order
    items = sorted_by_created([o for o in db.orders.values() if o["customer_id"] == cid])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_order(o) for o in page], limit, offset, total)


@bp.get("/customers/<cid>/subscriptions")
def customer_subscriptions(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    find_customer(cid)
    if role == "Customer" and user_id != cid:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    from routes.subscriptions import serialize_subscription
    items = sorted_by_created([s for s in db.subscriptions.values() if s["customer_id"] == cid])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_subscription(s) for s in page], limit, offset, total)
