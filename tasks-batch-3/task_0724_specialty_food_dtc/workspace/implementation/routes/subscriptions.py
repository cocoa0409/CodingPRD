from datetime import timedelta

from flask import Blueprint, request

from db import db, new_common, public, touch
from clock import clock, parse_iso, to_iso
from middleware import auth, require_role
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_NOT_DUE,
)
from helpers import (
    body,
    require_str,
    require_int,
    require_enum,
    find_customer,
    find_sku,
    find_subscription,
    paginate,
    sorted_by_created,
    TIERS,
    CADENCES,
)
from response import ok_object, ok_list
from services import calc, domain

bp = Blueprint("subscriptions", __name__)


def serialize_subscription(s):
    return public(s)


def _advance(sub, days):
    base = parse_iso(sub["next_renewal_iso"])
    sub["next_renewal_iso"] = to_iso(base + timedelta(days=days))


def _own_check(role, user_id, sub):
    if role == "Customer" and user_id != sub["customer_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")


@bp.post("/subscriptions")
def create_subscription():
    user_id, role = auth()
    require_role(role, {"Customer", "PlatformAdmin"})
    data = body()
    customer_id = require_str(data, "customer_id")
    sku_id = require_str(data, "sku_id")
    tier = require_str(data, "tier")
    # cadence required int
    if "cadence_days" not in data or data["cadence_days"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing cadence_days")
    cadence = data["cadence_days"]
    if isinstance(cadence, bool) or not isinstance(cadence, int):
        raise err(ERR_INVALID_REQUEST, "cadence_days must be an integer")
    # ownership: Customer creates for self
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    cust = find_customer(customer_id)
    sku = find_sku(sku_id)
    require_enum(tier, TIERS, "tier")
    if cadence not in CADENCES:
        raise err(ERR_INVALID_ENUM, "Invalid cadence_days")

    sid = db.new_id()
    sub = {
        "id": sid,
        "customer_id": customer_id,
        "sku_id": sku_id,
        "tier": tier,
        "cadence_days": cadence,
        "status": "ACTIVE",
        "next_renewal_iso": to_iso(clock.now() + timedelta(days=cadence)),
        "consecutive_skip_count": 0,
        "provisional_charge_cents": calc.provisional_charge(tier, cust["home_zone"]),
        "pending_swap_sku_id": None,
    }
    sub.update(new_common())
    db.subscriptions[sid] = sub
    return ok_object(serialize_subscription(sub), 201)


@bp.get("/subscriptions")
def list_subscriptions():
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    items = list(db.subscriptions.values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == user_id]
    for key in ("customer_id", "sku_id", "pending_swap_sku_id"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if s.get(key) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_subscription(s) for s in page], limit, offset, total)


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/subscriptions/<sid>/swap")
def swap_subscription(sid):
    user_id, role = auth()
    require_role(role, {"Customer"})
    data = body()
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    # request shape
    if "pending_swap_sku_id" not in data or data["pending_swap_sku_id"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing pending_swap_sku_id")
    if "expected_subscription_version" not in data or data["expected_subscription_version"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing expected_subscription_version")
    new_sku = data["pending_swap_sku_id"]
    expected = data["expected_subscription_version"]
    if not isinstance(new_sku, str):
        raise err(ERR_INVALID_REQUEST, "pending_swap_sku_id must be a string")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_subscription_version must be an integer")
    # existence of swap target (priority 4)
    find_sku(new_sku)
    # OCC (priority 7)
    if expected != sub["version"]:
        raise err(ERR_STALE_VERSION, "Stale subscription version")
    sub["pending_swap_sku_id"] = new_sku
    touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/subscriptions/<sid>/skip")
def skip_subscription(sid):
    user_id, role = auth()
    require_role(role, {"Customer"})
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    if sub["status"] != "ACTIVE" or sub["consecutive_skip_count"] >= 3:
        raise err(ERR_INVALID_STATE, "Cannot skip")
    sub["consecutive_skip_count"] += 1
    _advance(sub, sub["cadence_days"])
    if sub["consecutive_skip_count"] >= 3:
        sub["status"] = "PAUSED"
    touch(sub)
    cust = db.customers[sub["customer_id"]]
    cust["lifetime_skip_count"] += 1
    domain.record_event(cust, "skip")
    touch(cust)
    domain.recompute_customer_churn(cust)
    return ok_object(serialize_subscription(sub))


@bp.post("/subscriptions/<sid>/pause")
def pause_subscription(sid):
    user_id, role = auth()
    require_role(role, {"Customer"})
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    if sub["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Pause requires ACTIVE")
    sub["status"] = "PAUSED"
    touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/subscriptions/<sid>/resume")
def resume_subscription(sid):
    user_id, role = auth()
    require_role(role, {"Customer"})
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    if sub["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Resume requires PAUSED")
    sku = db.skus.get(sub["sku_id"])
    if sku is None or sku["status"] != "ACTIVE" or sku["available_units"] < 1:
        raise err(ERR_INVALID_STATE, "SKU not active or unavailable")
    sub["consecutive_skip_count"] = 0
    sub["next_renewal_iso"] = to_iso(clock.now() + timedelta(days=sub["cadence_days"]))
    sub["status"] = "ACTIVE"
    touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/subscriptions/<sid>/renew")
def renew_subscription(sid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Customer"})
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    if sub["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Renew requires ACTIVE")
    # temporal (priority 12)
    nri = parse_iso(sub["next_renewal_iso"])
    if clock.now() < nri:
        raise err(ERR_NOT_DUE, "Not due for renewal")
    # apply swap to determine effective sku
    if sub["pending_swap_sku_id"]:
        sub["sku_id"] = sub["pending_swap_sku_id"]
        sub["pending_swap_sku_id"] = None
    sku = db.skus.get(sub["sku_id"])
    if sku is None or sku["status"] != "ACTIVE" or sku["available_units"] < 1:
        raise err(ERR_INVALID_STATE, "SKU not active or unavailable")

    cust = db.customers[sub["customer_id"]]
    # create SUBSCRIPTION order with final charge
    from routes.orders import build_renewal_order
    final = calc.final_charge(sub["tier"], cust["home_zone"])
    build_renewal_order(cust, sub, final)

    _advance(sub, sub["cadence_days"])
    sub["consecutive_skip_count"] = 0
    touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    user_id, role = auth()
    require_role(role, {"Customer"})
    sub = find_subscription(sid)
    _own_check(role, user_id, sub)
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Cancel requires ACTIVE or PAUSED")
    sub["status"] = "CANCELLED"
    touch(sub)
    return ok_object(serialize_subscription(sub))
