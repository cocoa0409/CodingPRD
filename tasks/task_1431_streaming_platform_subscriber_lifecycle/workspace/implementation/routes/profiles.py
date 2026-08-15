"""Profile endpoints with household/sharing enforcement."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles, check_subscriber_ownership
from response import success_object, paginate
from util import new_uuid, stamp_new, touch

bp = Blueprint("profiles", __name__)


def _active_profiles(account_id):
    return [p for p in db.profiles.values()
            if p["account_id"] == account_id and p["profile_status"] == "ACTIVE"]


def _check_profile_caps(account):
    """Plan-rule checks for profile creation/reactivation (PRD §3.3)."""
    sub = None
    if account.get("active_subscription_id"):
        sub = db.subscriptions.get(account["active_subscription_id"])
    if sub is None:
        # No active subscription: cannot enforce plan limits; treat as violation
        raise ApiError("ERR_PLAN_RULE_VIOLATION", 422, "No active subscription")
    plan = db.plans.get(sub["plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_RULE_VIOLATION", 422, "Plan not found")
    active = _active_profiles(account["account_id"])
    if len(active) >= plan["max_profiles"]:
        raise ApiError("ERR_HOUSEHOLD_LIMIT_EXCEEDED", 422, "max_profiles reached")
    return sub, plan


def _check_households(account, plan, new_household_id):
    """Distinct household count across ACTIVE profiles must not exceed max_households."""
    active = _active_profiles(account["account_id"])
    households = {p["household_id"] for p in active}
    households.add(new_household_id)
    if len(households) > plan["max_households"]:
        raise ApiError("ERR_HOUSEHOLD_LIMIT_EXCEEDED", 422, "max_households exceeded")


@bp.route("/v1/profiles", methods=["POST"])
def create_profile():
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    body = request.get_json(silent=True) or {}
    for f in ["account_id", "display_name", "is_kids", "household_id"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    acct = db.accounts.get(body["account_id"])
    if not acct:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "account not found")
    check_subscriber_ownership(uid, role, acct["account_id"])
    if acct["account_status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is CLOSED")
    if acct["account_status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Account is SUSPENDED")
    sub, plan = _check_profile_caps(acct)
    _check_households(acct, plan, body["household_id"])
    prof = stamp_new({
        "profile_id": new_uuid(),
        "account_id": acct["account_id"],
        "display_name": body["display_name"],
        "is_kids": bool(body["is_kids"]),
        "household_id": body["household_id"],
        "profile_status": "ACTIVE",
    })
    db.profiles[prof["profile_id"]] = prof
    return success_object(prof, 201)


@bp.route("/v1/profiles", methods=["GET"])
def list_profiles():
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    items = list(db.profiles.values())
    if role == "Subscriber":
        items = [p for p in items if p["account_id"] == uid]
    for f in ["account_id", "profile_status", "household_id"]:
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if str(p.get(f)) == v]
    return paginate(items, request.args)


def _get_profile(pid):
    p = db.profiles.get(pid)
    if not p:
        raise ApiError("ERR_NOT_FOUND", 404, "profile not found")
    return p


@bp.route("/v1/profiles/<pid>", methods=["GET"])
def get_profile(pid):
    uid, role = require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    p = _get_profile(pid)
    check_subscriber_ownership(uid, role, p["account_id"])
    return success_object(p)


@bp.route("/v1/profiles/<pid>/deactivate", methods=["POST"])
def deactivate_profile(pid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    p = _get_profile(pid)
    check_subscriber_ownership(uid, role, p["account_id"])
    if p["profile_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Profile not ACTIVE")
    p["profile_status"] = "DEACTIVATED"
    touch(p)
    return success_object(p)


@bp.route("/v1/profiles/<pid>/reactivate", methods=["POST"])
def reactivate_profile(pid):
    uid, role = require_roles("Subscriber", "PlatformAdmin", "SupportAgent")
    p = _get_profile(pid)
    check_subscriber_ownership(uid, role, p["account_id"])
    if p["profile_status"] != "DEACTIVATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Profile not DEACTIVATED")
    acct = db.accounts.get(p["account_id"])
    if not acct or acct["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409, "Owning account not ACTIVE")
    sub = None
    if acct.get("active_subscription_id"):
        sub = db.subscriptions.get(acct["active_subscription_id"])
    if sub is None or sub["subscription_status"] not in ("TRIALING", "ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription state blocks reactivation")
    plan = db.plans.get(sub["plan_id"])
    active = _active_profiles(p["account_id"])
    if len(active) >= plan["max_profiles"]:
        raise ApiError("ERR_HOUSEHOLD_LIMIT_EXCEEDED", 422, "max_profiles reached")
    households = {q["household_id"] for q in active}
    households.add(p["household_id"])
    if len(households) > plan["max_households"]:
        raise ApiError("ERR_HOUSEHOLD_LIMIT_EXCEEDED", 422, "max_households exceeded")
    p["profile_status"] = "ACTIVE"
    touch(p)
    return success_object(p)
