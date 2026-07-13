"""Subscriptions: the two parallel state dimensions, tier changes and the
compensating revert (PRD §3.1, §3.2)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body, require_int

bp = Blueprint("subscriptions", __name__)

TIERS = ("FREE", "PLUS", "PRO")
EVENT_TYPES = ("PAYMENT_FAILED", "PAYMENT_SUCCEEDED", "CANCEL")


@bp.post("/dna/subscriptions")
@endpoint(["Customer", "PlatformAdmin"])
def create_subscription():
    payload = body()
    S.require_fields(payload, ["customer_id"])
    customer = S.get("customers", payload["customer_id"])
    require_owner(customer["id"])

    tier = payload.get("tier", "FREE")
    S.require_enum(tier, TIERS, "tier")

    S.require_not_purged(customer)

    start = db.now()
    sub = db.new_record(
        {
            "customer_id": customer["id"],
            "tier": tier,
            "pending_tier": None,
            "billing_status": "CURRENT",
            "access_status": "ACTIVE",
            "current_period_start": start,
            "current_period_end": start + db.days(calc.BILLING_PERIOD_DAYS),
            "grace_until": None,
            "lifetime_charged_cents": 0,
            "last_change_charge_cents": None,
            "last_change_from_tier": None,
        }
    )
    db.db.subscriptions[sub["id"]] = sub
    return ok(S.subscription_json(sub), 201)


@bp.get("/dna/subscriptions/<subscription_id>")
@endpoint(["Customer", "PlatformAdmin"])
def read_subscription(subscription_id):
    sub = S.get("subscriptions", subscription_id)
    require_owner(sub["customer_id"])
    return ok(S.subscription_json(sub))


@bp.get("/dna/subscriptions")
@endpoint(["Customer", "PlatformAdmin"])
def list_subscriptions():
    records = S.all_of("subscriptions")
    customer_id = request.args.get("customer_id")
    tier = request.args.get("tier")
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if tier:
        records = [r for r in records if r["tier"] == tier]
    return paginate(records, S.subscription_json)


@bp.post("/dna/subscriptions/<subscription_id>/change-tier")
@endpoint(["Customer"])
def change_tier(subscription_id):
    sub = S.get("subscriptions", subscription_id)
    require_owner(sub["customer_id"])

    payload = body()
    S.require_fields(payload, ["new_tier", "expected_subscription_version"])
    new_tier = payload["new_tier"]
    S.require_enum(new_tier, TIERS, "new_tier")
    expected = require_int(payload["expected_subscription_version"], "expected_subscription_version")

    if expected != sub["version"]:
        raise ApiError("ERR_STALE_VERSION")

    customer = db.db.customers[sub["customer_id"]]
    S.require_not_purged(customer)

    if sub["access_status"] not in ("ACTIVE", "GRACE"):
        raise ApiError("ERR_SUBSCRIPTION_LOCKED")

    old_tier = sub["tier"]
    is_upgrade, charge_total_cents = calc.tier_change_charge(
        old_tier, new_tier, sub["current_period_end"], db.now()
    )

    if is_upgrade:
        if customer["wallet_credit_cents"] < charge_total_cents:
            raise ApiError("ERR_INSUFFICIENT_CREDIT")
        sub["last_change_from_tier"] = old_tier
        sub["tier"] = new_tier
        customer["wallet_credit_cents"] = customer["wallet_credit_cents"] - charge_total_cents
        db.touch(customer)
        sub["lifetime_charged_cents"] = sub["lifetime_charged_cents"] + charge_total_cents
        sub["last_change_charge_cents"] = charge_total_cents
    else:
        sub["pending_tier"] = new_tier
        sub["last_change_charge_cents"] = 0
        sub["last_change_from_tier"] = old_tier

    db.touch(sub)
    return ok(S.subscription_json(sub))


@bp.post("/dna/subscriptions/<subscription_id>/revert-change")
@endpoint(["Customer"])
def revert_change(subscription_id):
    sub = S.get("subscriptions", subscription_id)
    require_owner(sub["customer_id"])

    customer = db.db.customers[sub["customer_id"]]
    S.require_not_purged(customer)

    if sub["last_change_charge_cents"] is None:
        raise ApiError("ERR_INVALID_STATE", "No tier change is outstanding.")
    if sub["access_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "The subscription is cancelled.")

    refund = sub["last_change_charge_cents"]
    customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + refund
    db.touch(customer)

    sub["lifetime_charged_cents"] = sub["lifetime_charged_cents"] - refund
    sub["tier"] = sub["last_change_from_tier"]
    sub["pending_tier"] = None
    sub["last_change_charge_cents"] = None
    sub["last_change_from_tier"] = None
    db.touch(sub)
    return ok(S.subscription_json(sub))


@bp.post("/dna/subscriptions/<subscription_id>/billing-event")
@endpoint(["PlatformAdmin"])
def billing_event(subscription_id):
    sub = S.get("subscriptions", subscription_id)
    payload = body()
    S.require_fields(payload, ["event_type"])
    event_type = payload["event_type"]
    S.require_enum(event_type, EVENT_TYPES, "event_type")

    customer = db.db.customers[sub["customer_id"]]
    S.require_not_purged(customer)

    if event_type == "PAYMENT_FAILED":
        _payment_failed(sub)
    elif event_type == "PAYMENT_SUCCEEDED":
        _payment_succeeded(sub)
    else:
        _cancel(sub, customer)

    db.touch(sub)
    return ok(S.subscription_json(sub))


def _payment_failed(sub):
    # Routed by the CURRENT PAIR of dimension values.
    if sub["billing_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    if sub["billing_status"] == "CURRENT" and sub["access_status"] == "ACTIVE":
        sub["billing_status"] = "PAST_DUE"
        sub["access_status"] = "GRACE"
        sub["grace_until"] = db.now() + db.days(calc.GRACE_PERIOD_DAYS)
        return
    if sub["billing_status"] == "PAST_DUE" and sub["access_status"] == "GRACE":
        # Only the access dimension advances; billing stays PAST_DUE.
        sub["access_status"] = "LOCKED"
        sub["grace_until"] = None
        return
    raise ApiError("ERR_INVALID_STATE")


def _payment_succeeded(sub):
    if sub["billing_status"] != "PAST_DUE":
        raise ApiError("ERR_INVALID_STATE")
    sub["billing_status"] = "CURRENT"
    sub["access_status"] = "ACTIVE"
    sub["grace_until"] = None


def _cancel(sub, customer):
    if sub["billing_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    refund = calc.subscription_close_refund(
        sub["tier"], sub["current_period_end"], db.now(), S.published_report_count(sub)
    )
    sub["billing_status"] = "CLOSED"
    sub["access_status"] = "CANCELLED"
    sub["pending_tier"] = None
    if refund:
        customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + refund
        db.touch(customer)
