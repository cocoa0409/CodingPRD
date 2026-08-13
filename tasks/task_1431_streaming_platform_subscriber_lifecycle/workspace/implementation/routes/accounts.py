"""Account endpoints including winback eligibility/enrollment."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles, check_subscriber_ownership
from response import success_object, paginate
from util import new_uuid, stamp_new, touch, round_half_up_cents
from services.domain import (
    suspend_account, deactivate_account_profiles, refresh_account_balance,
    live_subscription, most_recent_closed_subscription,
)
from services.billing import post_event
from util import parse_iso, whole_days
from decimal import Decimal

bp = Blueprint("accounts", __name__)


@bp.route("/v1/accounts", methods=["POST"])
def create_account():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    for f in ["email", "full_name", "country_code"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    # email globally unique
    for a in db.accounts.values():
        if a["email"] == body["email"]:
            raise ApiError("ERR_INVALID_REQUEST", 400, "email already in use")
    partner_id = body.get("created_via_partner_id")
    if partner_id is not None and partner_id not in db.partner_billing_records:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "created_via_partner_id not found")
    acct = stamp_new({
        "account_id": new_uuid(),
        "email": body["email"],
        "full_name": body["full_name"],
        "country_code": body["country_code"],
        "account_status": "ACTIVE",
        "created_via_partner_id": partner_id,
        "outstanding_balance_cents": 0,
        "active_subscription_id": None,
    })
    db.accounts[acct["account_id"]] = acct
    return success_object(acct, 201)


@bp.route("/v1/accounts", methods=["GET"])
def list_accounts():
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    items = list(db.accounts.values())
    for f in ["account_status", "email", "created_via_partner_id", "active_subscription_id"]:
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if str(a.get(f)) == v]
    return paginate(items, request.args)


def _get_account(aid):
    acct = db.accounts.get(aid)
    if not acct:
        raise ApiError("ERR_NOT_FOUND", 404, "account not found")
    return acct


@bp.route("/v1/accounts/<aid>", methods=["GET"])
def get_account(aid):
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    acct = _get_account(aid)
    check_subscriber_ownership(uid, role, acct["account_id"])
    refresh_account_balance(acct)
    return success_object(acct)


@bp.route("/v1/accounts/<aid>/suspend", methods=["POST"])
def suspend(aid):
    require_roles("PlatformAdmin")
    acct = _get_account(aid)
    if acct["account_status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is CLOSED")
    suspend_account(acct)
    return success_object(acct)


@bp.route("/v1/accounts/<aid>/unsuspend", methods=["POST"])
def unsuspend(aid):
    require_roles("PlatformAdmin", "SupportAgent")
    acct = _get_account(aid)
    if acct["account_status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is CLOSED")
    if acct["account_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Account not SUSPENDED")
    balance = refresh_account_balance(acct)
    if balance != 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 402, "Outstanding balance blocks unsuspend")
    acct["account_status"] = "ACTIVE"
    touch(acct)
    return success_object(acct)


@bp.route("/v1/accounts/<aid>/close", methods=["POST"])
def close(aid):
    require_roles("PlatformAdmin", "SupportAgent")
    acct = _get_account(aid)
    if acct["account_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Account already CLOSED")
    live = live_subscription(aid)
    if live is not None:
        raise ApiError("ERR_INVALID_STATE", 409, "Live subscription blocks close")
    balance = refresh_account_balance(acct)
    if balance != 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 402, "Outstanding balance blocks close")
    acct["account_status"] = "CLOSED"
    touch(acct)
    deactivate_account_profiles(acct)
    return success_object(acct)


@bp.route("/v1/accounts/<aid>/winback-eligibility", methods=["GET"])
def winback_eligibility(aid):
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "Subscriber")
    acct = _get_account(aid)
    check_subscriber_ownership(uid, role, acct["account_id"])
    sub = most_recent_closed_subscription(aid)
    if sub is None:
        return success_object({"eligible_campaign_ids": [], "days_since_cancel": 0})
    days_since = whole_days(db.get_now(), parse_iso(sub["updated_at"]))
    campaigns = [c for c in db.winback_campaigns.values()
                 if c["campaign_status"] == "ACTIVE"
                 and c["min_days_since_cancel"] <= days_since <= c["max_days_since_cancel"]
                 and sub.get("cancel_reason") in c["eligible_cancel_reasons"]]
    campaigns.sort(key=lambda c: c["created_at"])
    return success_object({
        "eligible_campaign_ids": [c["winback_campaign_id"] for c in campaigns],
        "days_since_cancel": days_since,
    })


@bp.route("/v1/accounts/<aid>/winback-enroll", methods=["POST"])
def winback_enroll(aid):
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "Subscriber")
    acct = _get_account(aid)
    check_subscriber_ownership(uid, role, acct["account_id"])
    if acct["account_status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is CLOSED")
    body = request.get_json(silent=True) or {}
    campaign_id = body.get("winback_campaign_id")
    expected_version = body.get("expected_subscription_version")
    if not campaign_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "winback_campaign_id required")
    campaign = db.winback_campaigns.get(campaign_id)
    if not campaign:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "campaign not found")
    sub = most_recent_closed_subscription(aid)
    if sub is None:
        raise ApiError("ERR_WINBACK_INELIGIBLE", 422, "No cancelled/expired subscription")
    # OCC check
    if expected_version is not None and expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale subscription version")
    # Eligibility check
    days_since = whole_days(db.get_now(), parse_iso(sub["updated_at"]))
    eligible = (campaign["campaign_status"] == "ACTIVE"
                and campaign["min_days_since_cancel"] <= days_since <= campaign["max_days_since_cancel"]
                and sub.get("cancel_reason") in campaign["eligible_cancel_reasons"])
    if not eligible:
        raise ApiError("ERR_WINBACK_INELIGIBLE", 422, "Account not eligible for campaign")
    plan = db.plans.get(sub["plan_id"])
    discounted = round_half_up_cents(
        Decimal(plan["monthly_price_cents"]) * (100 - campaign["discount_pct"]) / 100)
    sub["subscription_status"] = "ACTIVE"
    sub["grandfathered_price_cents"] = discounted
    touch(sub)
    acct["active_subscription_id"] = sub["subscription_id"]
    touch(acct)
    post_event(aid, sub["subscription_id"], "CHARGE", discounted)
    return success_object(sub)
