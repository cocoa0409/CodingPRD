"""Save offer endpoints."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles, check_subscriber_ownership
from response import success_object, paginate
from util import new_uuid, stamp_new, touch, format_ts, parse_iso, round_half_up_cents
from services.domain import apply_pause

bp = Blueprint("save_offers", __name__)

OFFER_TYPES = {"PAUSE_1M", "PAUSE_3M", "DOWNGRADE", "DISCOUNT_50_3M"}


@bp.route("/v1/save-offers", methods=["POST"])
def create_offer():
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    body = request.get_json(silent=True) or {}
    for f in ["subscription_id", "offer_type"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    if body["offer_type"] not in OFFER_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid offer_type")
    sub = db.subscriptions.get(body["subscription_id"])
    if not sub:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "subscription not found")
    check_subscriber_ownership(uid, role, sub["account_id"])
    target_plan_id = body.get("target_plan_id")
    if body["offer_type"] == "DOWNGRADE":
        if not target_plan_id or target_plan_id not in db.plans:
            raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "target_plan_id not found")
    else:
        target_plan_id = None
    discount_pct = body.get("discount_pct", 0)
    discount_duration = body.get("discount_duration_months", 0)
    if body["offer_type"] != "DISCOUNT_50_3M":
        discount_pct = 0
        discount_duration = 0
    # Supersede any PRESENTED offer on this subscription
    for o in db.save_offers.values():
        if o["subscription_id"] == sub["subscription_id"] and o["offer_status"] == "PRESENTED":
            o["offer_status"] = "SUPERSEDED"
            touch(o)
    now = db.get_now()
    offer = stamp_new({
        "save_offer_id": new_uuid(),
        "account_id": sub["account_id"],
        "subscription_id": sub["subscription_id"],
        "offer_type": body["offer_type"],
        "offer_status": "PRESENTED",
        "discount_pct": discount_pct,
        "discount_duration_months": discount_duration,
        "target_plan_id": target_plan_id,
        "presented_at_utc": format_ts(now),
        "expires_at_utc": format_ts(now + timedelta(hours=72)),
    })
    db.save_offers[offer["save_offer_id"]] = offer
    sub["save_offer_id"] = offer["save_offer_id"]
    touch(sub)
    return success_object(offer, 201)


@bp.route("/v1/save-offers", methods=["GET"])
def list_offers():
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "Subscriber")
    items = list(db.save_offers.values())
    if role == "Subscriber":
        items = [o for o in items if o["account_id"] == uid]
    for f in ["subscription_id", "offer_status", "offer_type", "account_id", "target_plan_id"]:
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if str(o.get(f)) == v]
    return paginate(items, request.args)


def _get_offer(oid):
    o = db.save_offers.get(oid)
    if not o:
        raise ApiError("ERR_NOT_FOUND", 404, "save offer not found")
    return o


@bp.route("/v1/save-offers/<oid>", methods=["GET"])
def get_offer(oid):
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "Subscriber")
    o = _get_offer(oid)
    check_subscriber_ownership(uid, role, o["account_id"])
    return success_object(o)


@bp.route("/v1/save-offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    uid, role = require_roles("Subscriber")
    o = _get_offer(oid)
    check_subscriber_ownership(uid, role, o["account_id"])
    if o["offer_status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer not PRESENTED")
    sub = db.subscriptions.get(o["subscription_id"])
    if not sub:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "subscription missing")
    if sub["subscription_status"] not in ("ACTIVE", "TRIALING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription state blocks acceptance")
    if db.get_now() >= parse_iso(o["expires_at_utc"]):
        raise ApiError("ERR_OFFER_EXPIRED", 422, "Offer expired")
    o["offer_status"] = "ACCEPTED"
    touch(o)
    if o["offer_type"] == "PAUSE_1M":
        if sub["subscription_status"] == "ACTIVE":
            apply_pause(sub, 1)
        else:
            sub["subscription_status"] = "PAUSED"
            from util import add_months
            sub["paused_until_utc"] = format_ts(add_months(db.get_now(), 1))
            touch(sub)
    elif o["offer_type"] == "PAUSE_3M":
        if sub["subscription_status"] == "ACTIVE":
            apply_pause(sub, 3)
        else:
            sub["subscription_status"] = "PAUSED"
            from util import add_months
            sub["paused_until_utc"] = format_ts(add_months(db.get_now(), 3))
            touch(sub)
    elif o["offer_type"] == "DOWNGRADE":
        sub["pending_plan_id"] = o["target_plan_id"]
        touch(sub)
    elif o["offer_type"] == "DISCOUNT_50_3M":
        plan = db.plans.get(sub["plan_id"])
        base = sub.get("grandfathered_price_cents")
        if base is None:
            base = plan["monthly_price_cents"]
        pct = o["discount_pct"]
        if pct >= 100:
            discounted = 0
        elif pct <= 0:
            discounted = base
        else:
            discounted = round_half_up_cents(Decimal(base) * (100 - pct) / 100)
        sub["grandfathered_price_cents"] = discounted
        touch(sub)
    return success_object(o)


@bp.route("/v1/save-offers/<oid>/decline", methods=["POST"])
def decline_offer(oid):
    uid, role = require_roles("Subscriber")
    o = _get_offer(oid)
    check_subscriber_ownership(uid, role, o["account_id"])
    if o["offer_status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer not PRESENTED")
    o["offer_status"] = "DECLINED"
    touch(o)
    return success_object(o)
