"""Subscription endpoints: create, cancel, pause, resume, recover, change-plan, preview."""
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles, check_subscriber_ownership
from response import success_object, paginate
from util import new_uuid, stamp_new, touch, format_ts, parse_iso
from services.billing import (
    post_event, current_price_cents, payment_will_succeed,
    proration_components, DAYS_PER_PERIOD_NOMINAL, MAX_DUNNING_ATTEMPTS,
)
from services.domain import (
    TIER_ORDER, LIVE_SUBSCRIPTION_STATUSES, live_subscription,
    cancel_subscription, apply_pause, apply_resume, apply_plan_change_upgrade,
)

bp = Blueprint("subscriptions", __name__)


@bp.route("/v1/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    body = request.get_json(silent=True) or {}
    for f in ["account_id", "plan_id"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    acct = db.accounts.get(body["account_id"])
    plan = db.plans.get(body["plan_id"])
    if not acct or not plan:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "account or plan not found")
    check_subscriber_ownership(uid, role, acct["account_id"])
    if acct["account_status"] in ("SUSPENDED", "CLOSED"):
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account not ACTIVE")
    if plan["is_archived"]:
        raise ApiError("ERR_PLAN_RULE_VIOLATION", 422, "Plan is archived")
    # One live subscription per account
    for s in db.subscriptions.values():
        if s["account_id"] == acct["account_id"] and s["subscription_status"] in LIVE_SUBSCRIPTION_STATUSES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_SUBSCRIPTION", 409,
                           "Account already has a live subscription")
    now = db.get_now()
    content_id = body.get("content_id", "")
    channel = body.get("channel", "ORGANIC")
    valid_channels = {"ORGANIC", "SEARCH", "SOCIAL", "AD", "EMAIL", "REFERRAL"}
    if channel not in valid_channels:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid channel")

    period_start = now
    period_end = now + timedelta(days=DAYS_PER_PERIOD_NOMINAL)
    trial_days = plan["trial_days"]

    # Optional payment-method token supplied at signup decides charge success
    pm_token = body.get("payment_method_token")
    if pm_token is not None:
        acct["_payment_method_token"] = pm_token

    sub = {
        "subscription_id": new_uuid(),
        "account_id": acct["account_id"],
        "plan_id": plan["plan_id"],
        "subscription_status": None,
        "billing_state": "CURRENT",
        "cancel_reason": None,
        "period_start_utc": format_ts(period_start),
        "period_end_utc": format_ts(period_end),
        "trial_end_utc": None,
        "paused_until_utc": None,
        "pending_plan_id": None,
        "grandfathered_price_cents": None,
        "save_offer_id": None,
        "signup_attribution_id": None,
        "dunning_attempt_count": 0,
        "price_change_notice_id": None,
    }

    if trial_days > 0:
        sub["subscription_status"] = "TRIALING"
        sub["trial_end_utc"] = format_ts(now + timedelta(days=trial_days))
        stamp_new(sub)
        db.subscriptions[sub["subscription_id"]] = sub
        post_event(acct["account_id"], sub["subscription_id"], "TRIAL_START", 0)
    else:
        # No trial: first charge attempted immediately. An explicitly failing
        # token rejects the creation; absent token means a valid method is on
        # file (PRD §3.2 names no creation-time payment-token requirement).
        if pm_token is not None and not payment_will_succeed(pm_token):
            raise ApiError("ERR_PAYMENT_FAILED", 402, "First charge failed")
        sub["subscription_status"] = "ACTIVE"
        stamp_new(sub)
        db.subscriptions[sub["subscription_id"]] = sub
        post_event(acct["account_id"], sub["subscription_id"], "CHARGE",
                   current_price_cents(sub))

    # Signup attribution
    attr = stamp_new({
        "signup_attribution_id": new_uuid(),
        "account_id": acct["account_id"],
        "subscription_id": sub["subscription_id"],
        "content_id": content_id,
        "channel": channel,
        "cohort_month": sub["created_at"][:7],
        "retained_at_day_30": False,
        "retained_at_day_90": False,
    })
    db.signup_attributions[attr["signup_attribution_id"]] = attr
    sub["signup_attribution_id"] = attr["signup_attribution_id"]
    touch(sub)

    acct["active_subscription_id"] = sub["subscription_id"]
    touch(acct)
    return success_object(sub, 201)


@bp.route("/v1/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    items = list(db.subscriptions.values())
    if role == "Subscriber":
        items = [s for s in items if s["account_id"] == uid]
    for f in ["account_id", "subscription_status", "plan_id", "billing_state",
              "pending_plan_id", "save_offer_id", "signup_attribution_id",
              "price_change_notice_id"]:
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s.get(f)) == v]
    return paginate(items, request.args)


def _get_sub(sid):
    sub = db.subscriptions.get(sid)
    if not sub:
        raise ApiError("ERR_NOT_FOUND", 404, "subscription not found")
    return sub


def _own_or_staff(uid, role, sub):
    check_subscriber_ownership(uid, role, sub["account_id"])


def _check_account_allows(sub):
    acct = db.accounts.get(sub["account_id"])
    if acct and acct["account_status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is CLOSED")
    return acct


@bp.route("/v1/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    return success_object(sub)


@bp.route("/v1/subscriptions/<sid>/cancel", methods=["POST"])
def cancel(sid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    _check_account_allows(sub)
    body = request.get_json(silent=True) or {}
    reason = body.get("cancel_reason")
    valid = {"USER_REQUESTED", "PAYMENT_FAILED", "PRICE_REFUSAL", "WINBACK_EXPIRED", "ADMIN"}
    if reason is not None and reason not in valid:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid cancel_reason")
    if sub["subscription_status"] not in ("TRIALING", "ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription cannot be cancelled")
    if reason is None:
        reason = "USER_REQUESTED" if role == "Subscriber" else "ADMIN"
    cancel_subscription(sub, reason)
    return success_object(sub)


@bp.route("/v1/subscriptions/<sid>/pause", methods=["POST"])
def pause(sid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    acct = _check_account_allows(sub)
    if acct and acct["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is SUSPENDED")
    body = request.get_json(silent=True) or {}
    duration = body.get("duration_months")
    if duration is None or not isinstance(duration, int) or duration <= 0:
        raise ApiError("ERR_OFFER_EXPIRED", 422, "Invalid pause duration")
    if sub["subscription_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not ACTIVE")
    # 12-month cooldown on direct pause
    last_pause = sub.get("_last_pause_at")
    if last_pause:
        from util import whole_days
        if whole_days(db.get_now(), parse_iso(last_pause)) < 365:
            raise ApiError("ERR_PAUSE_NOT_ALLOWED", 422, "Paused within trailing 12 months")
    apply_pause(sub, duration)
    return success_object(sub)


@bp.route("/v1/subscriptions/<sid>/resume", methods=["POST"])
def resume(sid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    acct = _check_account_allows(sub)
    if acct and acct["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is SUSPENDED")
    if sub["subscription_status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not PAUSED")
    apply_resume(sub)
    return success_object(sub)


@bp.route("/v1/subscriptions/<sid>/recover", methods=["POST"])
def recover(sid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    acct = _check_account_allows(sub)
    if acct and acct["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is SUSPENDED")
    body = request.get_json(silent=True) or {}
    token = body.get("payment_method_token")
    if not token:
        raise ApiError("ERR_INVALID_REQUEST", 400, "payment_method_token required")
    if sub["subscription_status"] != "PAST_DUE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not PAST_DUE")
    if sub.get("dunning_attempt_count", 0) >= MAX_DUNNING_ATTEMPTS:
        raise ApiError("ERR_DUNNING_EXHAUSTED", 409, "Dunning exhausted")
    if not payment_will_succeed(token):
        raise ApiError("ERR_PAYMENT_FAILED", 402, "Replacement payment method failed")
    # Success: PAST_DUE → ACTIVE, DUNNING → RECOVERED, reset count, RECOVERY event
    acct["_payment_method_token"] = token
    recovered_amount = current_price_cents(sub)
    sub["subscription_status"] = "ACTIVE"
    sub["billing_state"] = "RECOVERED"
    sub["dunning_attempt_count"] = 0
    touch(sub)
    post_event(sub["account_id"], sub["subscription_id"], "RECOVERY", recovered_amount)
    return success_object(sub)


@bp.route("/v1/subscriptions/<sid>/change-plan", methods=["POST"])
def change_plan(sid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    acct = _check_account_allows(sub)
    if acct and acct["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is SUSPENDED")
    body = request.get_json(silent=True) or {}
    target_plan_id = body.get("target_plan_id")
    expected_version = body.get("expected_subscription_version")
    if not target_plan_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_plan_id required")
    if sub["subscription_status"] not in ("TRIALING", "ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription state blocks plan change")
    # OCC
    if expected_version is not None and expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale subscription version")
    target = db.plans.get(target_plan_id)
    if not target:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "target plan not found")
    if target["is_archived"]:
        raise ApiError("ERR_PLAN_RULE_VIOLATION", 422, "Target plan archived")
    current_plan = db.plans.get(sub["plan_id"])
    if TIER_ORDER[target["tier"]] > TIER_ORDER[current_plan["tier"]]:
        apply_plan_change_upgrade(sub, target)
    elif TIER_ORDER[target["tier"]] < TIER_ORDER[current_plan["tier"]]:
        sub["pending_plan_id"] = target_plan_id
        touch(sub)
    else:
        raise ApiError("ERR_PLAN_RULE_VIOLATION", 422, "Same tier is not a valid change")
    return success_object(sub)


@bp.route("/v1/subscriptions/<sid>/proration-preview", methods=["GET"])
def proration_preview(sid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    sub = _get_sub(sid)
    _own_or_staff(uid, role, sub)
    target_plan_id = request.args.get("target_plan_id")
    if not target_plan_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_plan_id required")
    target = db.plans.get(target_plan_id)
    if not target:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "target plan not found")
    comp = proration_components(sub, target, db.get_now())
    return success_object(comp)
