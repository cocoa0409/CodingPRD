"""Subscription plans and subscriptions."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_iso
from errors import err
from helpers import (body, require_fields, require_str, require_int, require_bool,
                     get_or_404, fk_or_404, paginate, filter_by)
from middleware import get_auth, require_roles, require_owner
from response import success, now_iso
from serializers import serialize


bp = Blueprint("subscriptions", __name__)


def _iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------- Plans ----------------
@bp.post("/subscription-plans")
def create_plan():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["tier_name", "monthly_fee_cents"])
    require_str(data, "tier_name")
    require_int(data, "monthly_fee_cents")
    require_bool(data, "free_delivery")
    require_int(data, "points_multiplier_bps")
    if data["monthly_fee_cents"] < 0:
        raise err("ERR_INVALID_REQUEST", "monthly_fee_cents must be >= 0.")
    mult = data.get("points_multiplier_bps", 10000)
    if mult is None:
        mult = 10000
    if mult < 10000:
        raise err("ERR_INVALID_REQUEST", "points_multiplier_bps must be >= 10000.")
    free_delivery = data.get("free_delivery", False)
    if free_delivery is None:
        free_delivery = False
    # unique tier_name
    for p in db.subscription_plans.values():
        if p["tier_name"] == data["tier_name"]:
            raise err("ERR_INVALID_REQUEST", "tier_name must be unique.")

    plan = db.common_fields()
    plan.update({
        "tier_name": data["tier_name"],
        "monthly_fee_cents": data["monthly_fee_cents"],
        "free_delivery": free_delivery,
        "points_multiplier_bps": mult,
    })
    db.subscription_plans[plan["id"]] = plan
    return success(serialize("subscription_plan", plan), 201)


# ---------------- Subscriptions ----------------
@bp.post("/subscriptions")
def create_subscription():
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    data = body()
    require_fields(data, ["customer_id", "plan_id"])
    require_str(data, "customer_id")
    require_str(data, "plan_id")
    require_owner(role, user_id, data["customer_id"])
    fk_or_404("customer", data["customer_id"])
    fk_or_404("subscription_plan", data["plan_id"])

    sub = db.common_fields()
    sub.update({
        "customer_id": data["customer_id"],
        "plan_id": data["plan_id"],
        "status": "PENDING_PAYMENT",
        "current_period_end_utc": None,
    })
    db.subscriptions[sub["id"]] = sub
    return success(serialize("subscription", sub), 201)


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    get_auth()
    sub = get_or_404("subscription", sid)
    return success(serialize("subscription", sub), 200)


@bp.get("/subscriptions")
def list_subscriptions():
    get_auth()
    customer_id = request.args.get("customer_id")
    plan_id = request.args.get("plan_id")
    items = filter_by(db.subscriptions, customer_id=customer_id, plan_id=plan_id)
    page, meta = paginate(items)
    return success([serialize("subscription", s) for s in page], 200, meta)


@bp.post("/subscriptions/<sid>/pay")
def pay_subscription(sid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    sub = get_or_404("subscription", sid)
    require_owner(role, user_id, sub["customer_id"])
    data = body()
    require_fields(data, ["payment_outcome"])
    require_str(data, "payment_outcome")
    # state: only PENDING_PAYMENT or PAST_DUE -> ACTIVE
    if sub["status"] not in {"PENDING_PAYMENT", "PAST_DUE"}:
        raise err("ERR_INVALID_STATE", "Subscription not payable from current state.")
    if data["payment_outcome"] != "SUCCEEDED":
        raise err("ERR_PAYMENT_FAILED", "Payment outcome not SUCCEEDED.")
    sub["status"] = "ACTIVE"
    sub["current_period_end_utc"] = _iso_z(db.clock_dt() + timedelta(days=30))
    db.touch(sub)
    return success(serialize("subscription", sub), 200)


@bp.post("/subscriptions/<sid>/lapse")
def lapse_subscription(sid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    sub = get_or_404("subscription", sid)
    if sub["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only ACTIVE subscriptions may lapse.")
    period_end = parse_iso(sub["current_period_end_utc"])
    if period_end is None or db.clock_dt() < period_end:
        raise err("ERR_INVALID_STATE", "Subscription period has not ended.")
    sub["status"] = "PAST_DUE"
    db.touch(sub)
    return success(serialize("subscription", sub), 200)


@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    sub = get_or_404("subscription", sid)
    require_owner(role, user_id, sub["customer_id"])
    if sub["status"] not in {"ACTIVE", "PAST_DUE"}:
        raise err("ERR_INVALID_STATE", "Subscription not cancellable from current state.")
    sub["status"] = "CANCELLED"
    db.touch(sub)
    return success(serialize("subscription", sub), 200)
