"""Subscription routes: create, list, get, convert, change-plan, cancel, add-ons,
pause-windows, usage (PRD §3.2, §3.3, §3.4, §3.5, §3.9)."""
from flask import Blueprint, request

import errors
import serializers as S
import validate as V
from db import db, stamp_new, touch
from middleware import authenticate, require_role, require_account_owner_match
from response import success
from util import (
    parse_dt, parse_pagination, paginate, sort_by_created,
    add_days, CYCLE_DAYS, MIN_PAUSE_GAP_DAYS,
)
from services import billing

bp = Blueprint("subscriptions", __name__)


# ---- shared resolution helpers ---------------------------------------------
def _get_account_or_404(account_id):
    account = db.accounts.get(account_id)
    if account is None:
        raise errors.not_found("Account not found")
    return account


def _get_sub_under_account(account_id, sid):
    """Validate account then subscription left-to-right (PRD §2.8)."""
    account = _get_account_or_404(account_id)
    sub = db.subscriptions.get(sid)
    if sub is None or sub["account_id"] != account_id:
        raise errors.not_found("Subscription not found")
    return account, sub


# =============================================================================
# Create subscription (PRD §3.2)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions", methods=["POST"])
def create_subscription(id):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account = _get_account_or_404(id)
    require_account_owner_match(role, user_id, id)

    body = V.get_body()
    # Body FK existence (priority 4) before body well-formedness checks happen
    # naturally as we resolve; required field plan_id (priority 5) first.
    if "plan_id" not in body or body["plan_id"] is None:
        raise errors.invalid_request("Missing required field: plan_id")
    plan_id = body["plan_id"]
    if not isinstance(plan_id, str):
        raise errors.invalid_request("plan_id must be a string")
    plan = db.plans.get(plan_id)
    if plan is None:
        raise errors.reference_not_found("plan_id does not resolve")

    coupon = None
    coupon_id = body.get("coupon_id")
    if coupon_id is not None:
        if not isinstance(coupon_id, str):
            raise errors.invalid_request("coupon_id must be a string")
        coupon = db.coupons.get(coupon_id)
        if coupon is None:
            raise errors.reference_not_found("coupon_id does not resolve")

    # State: plan not archived (priority 9 -> ERR_PLAN_ARCHIVED).
    if plan["status"] == "ARCHIVED":
        raise errors.ApiError(errors.ERR_PLAN_ARCHIVED, 409,
                              "Cannot subscribe to an archived plan")

    # Coupon redeemable (priority 10 -> ERR_COUPON_NOT_REDEEMABLE).
    if coupon is not None:
        _ensure_coupon_redeemable(coupon)

    now = db.now()
    sub = {
        "account_id": id,
        "plan_id": plan_id,
        "coupon_id": coupon_id,
        "period_start": now,
        "period_end": add_days(now, CYCLE_DAYS),
        "trial_end": None,
        "lifecycle_status": "TRIALING",
        "billing_status": "CURRENT",
        "dunning_attempt": 0,
        "next_retry_at": None,
        "mrr_contribution_cents": 0,
    }
    stamp_new(sub)
    db.subscriptions[sub["id"]] = sub

    if plan["trial_days"] > 0:
        # TRIALING: trial_end = now + trial_days; no invoice (PRD §3.2).
        sub["lifecycle_status"] = "TRIALING"
        sub["trial_end"] = add_days(now, plan["trial_days"])
        sub["mrr_contribution_cents"] = 0
    else:
        # ACTIVE directly: set period, finalize first invoice, attempt payment.
        sub["lifecycle_status"] = "ACTIVE"
        sub["trial_end"] = None
        billing.build_cycle_invoice(sub, account, plan,
                                    sub["period_start"], sub["period_end"],
                                    include_overage=True)
        billing.reconcile_subscription_and_account(sub)

    # Redeem coupon (PRD §3.2): increment redemption_count, flip EXHAUSTED.
    if coupon is not None:
        _redeem_coupon(coupon)

    # MRR reconcile for the trialing case keeps contribution at 0; harmless.
    billing.reconcile_subscription_and_account(sub)
    return success(S.ser_subscription(sub), status=201)


def _ensure_coupon_redeemable(coupon):
    if coupon["status"] != "ACTIVE" or coupon["redemption_count"] >= coupon["max_redemptions"]:
        raise errors.ApiError(errors.ERR_COUPON_NOT_REDEEMABLE, 409,
                              "Coupon is not redeemable")


def _redeem_coupon(coupon):
    coupon["redemption_count"] += 1
    if coupon["redemption_count"] >= coupon["max_redemptions"]:
        coupon["status"] = "EXHAUSTED"
    touch(coupon)


@bp.route("/accounts/<id>/subscriptions", methods=["GET"])
def list_account_subscriptions(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    _get_account_or_404(id)
    require_account_owner_match(role, user_id, id)
    limit, offset = parse_pagination()
    items = [s for s in db.subscriptions.values() if s["account_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_subscription(s) for s in page], is_array=True, pagination=pg)


@bp.route("/subscriptions/<id>", methods=["GET"])
def get_subscription(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    sub = db.subscriptions.get(id)
    if sub is None:
        raise errors.not_found("Subscription not found")
    require_account_owner_match(role, user_id, sub["account_id"])
    return success(S.ser_subscription(sub))


# =============================================================================
# Convert trial early (PRD §3.3)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions/<sid>/convert", methods=["POST"])
def convert_subscription(id, sid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    if sub["lifecycle_status"] != "TRIALING":
        raise errors.invalid_state("Subscription is not TRIALING")

    plan = db.plans.get(sub["plan_id"])
    if plan is None or plan["status"] == "ARCHIVED":
        raise errors.ApiError(errors.ERR_PLAN_ARCHIVED, 409,
                              "Plan is archived; cannot convert")

    now = db.now()
    sub["lifecycle_status"] = "ACTIVE"
    sub["period_start"] = now
    sub["period_end"] = add_days(now, CYCLE_DAYS)
    touch(sub)

    billing.build_cycle_invoice(sub, account, plan,
                                sub["period_start"], sub["period_end"],
                                include_overage=True)
    billing.reconcile_subscription_and_account(sub)
    return success(S.ser_subscription(sub))


# =============================================================================
# Change plan with proration (PRD §3.5, OCC §2.6)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions/<sid>/change-plan", methods=["POST"])
def change_plan(id, sid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    body = V.get_body()
    # Body FK existence (priority 4) for plan_id.
    if "plan_id" not in body or body["plan_id"] is None:
        raise errors.invalid_request("Missing required field: plan_id")
    new_plan_id = body["plan_id"]
    if not isinstance(new_plan_id, str):
        raise errors.invalid_request("plan_id must be a string")
    new_plan = db.plans.get(new_plan_id)
    if new_plan is None:
        raise errors.reference_not_found("plan_id does not resolve")

    coupon = None
    coupon_id = body.get("coupon_id")
    if coupon_id is not None:
        if not isinstance(coupon_id, str):
            raise errors.invalid_request("coupon_id must be a string")
        coupon = db.coupons.get(coupon_id)
        if coupon is None:
            raise errors.reference_not_found("coupon_id does not resolve")

    # Body well-formedness (priority 5): expected_subscription_version required.
    if "expected_subscription_version" not in body or body["expected_subscription_version"] is None:
        raise errors.invalid_request("Missing required field: expected_subscription_version")
    expected = body["expected_subscription_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_subscription_version must be an integer")

    # State: subscription must be ACTIVE (priority 7 -> ERR_INVALID_STATE).
    if sub["lifecycle_status"] != "ACTIVE":
        raise errors.invalid_state("Subscription must be ACTIVE to change plan")

    # Plan archived (priority 9).
    if new_plan["status"] == "ARCHIVED":
        raise errors.ApiError(errors.ERR_PLAN_ARCHIVED, 409,
                              "Target plan is archived")

    # Coupon redeemable when adding one (priority 10).
    if coupon is not None:
        _ensure_coupon_redeemable(coupon)

    # No-op change (priority 11 -> ERR_NO_PLAN_CHANGE).
    if new_plan_id == sub["plan_id"]:
        raise errors.ApiError(errors.ERR_NO_PLAN_CHANGE, 409,
                              "Target plan equals the current plan")

    # OCC (priority 14 -> ERR_STALE_VERSION 412).
    if expected != sub["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_subscription_version does not match")

    old_plan = db.plans.get(sub["plan_id"])

    # Proration invoice (PRD §3.5): credit + charge lines, finalize.
    billing.build_proration_invoice(sub, account, old_plan, new_plan)

    # Completing the change: bump version, set new plan, recompute MRR (PRD §3.5).
    sub["plan_id"] = new_plan_id
    if coupon is not None:
        sub["coupon_id"] = coupon_id
        _redeem_coupon(coupon)
    touch(sub)  # increments version by one
    billing.reconcile_subscription_and_account(sub)
    return success(S.ser_subscription(sub))


# =============================================================================
# Cancel subscription (PRD §3.9)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(id, sid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    status = sub["lifecycle_status"]
    if status not in ("ACTIVE", "TRIALING"):
        raise errors.invalid_state("Subscription is not in a cancelable state")

    if status == "ACTIVE":
        # Capture the recurring revenue lost to this voluntary churn (PRD §3.8).
        lost_mrr = sub["mrr_contribution_cents"]
        billing.record_churn(sub, lost_mrr)
        sub["lifecycle_status"] = "CANCELED"
        sub["mrr_contribution_cents"] = 0
        touch(sub)
        # VOID unpaid DRAFT/OPEN invoices (amount_paid_cents == 0).
        for inv in db.invoices.values():
            if inv["subscription_id"] != sid:
                continue
            if inv["status"] in ("DRAFT", "OPEN") and inv["amount_paid_cents"] == 0:
                inv["status"] = "VOID"
                touch(inv)
        # Mark all add-ons REMOVED.
        for sa in db.subscription_addons.values():
            if sa["subscription_id"] == sid and sa["status"] == "ACTIVE":
                sa["status"] = "REMOVED"
                touch(sa)
        billing.reconcile_subscription_and_account(sub)
    else:  # TRIALING
        sub["lifecycle_status"] = "CANCELED"
        touch(sub)
        # No invoice ever generated; already excluded from MRR -> no delta.

    return success(S.ser_subscription(sub))


# =============================================================================
# Subscription add-ons (PRD §3.9)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions/<sid>/addons", methods=["POST"])
def add_addon(id, sid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    body = V.get_body()
    if "addon_id" not in body or body["addon_id"] is None:
        raise errors.invalid_request("Missing required field: addon_id")
    addon_id = body["addon_id"]
    if not isinstance(addon_id, str):
        raise errors.invalid_request("addon_id must be a string")
    addon = db.addons.get(addon_id)
    if addon is None:
        raise errors.reference_not_found("addon_id does not resolve")

    # Duplicate active add-on (priority 13 -> ERR_ADDON_ALREADY_ACTIVE).
    for sa in db.subscription_addons.values():
        if (sa["subscription_id"] == sid and sa["addon_id"] == addon_id
                and sa["status"] == "ACTIVE"):
            raise errors.ApiError(errors.ERR_ADDON_ALREADY_ACTIVE, 409,
                                  "Add-on already active on this subscription")

    sa = {"subscription_id": sid, "addon_id": addon_id, "status": "ACTIVE"}
    stamp_new(sa)
    db.subscription_addons[sa["id"]] = sa
    # A child fact (add-on set) changed, so the subscription's derived MRR and
    # its updated_at/version refresh in the same operation (PRD §2.9).
    touch(sub)
    billing.reconcile_subscription_and_account(sub)
    return success(S.ser_subscription_addon(sa), status=201)


@bp.route("/subscriptions/<id>/addons", methods=["GET"])
def list_subscription_addons(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    sub = db.subscriptions.get(id)
    if sub is None:
        raise errors.not_found("Subscription not found")
    require_account_owner_match(role, user_id, sub["account_id"])
    limit, offset = parse_pagination()
    items = [sa for sa in db.subscription_addons.values() if sa["subscription_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_subscription_addon(sa) for sa in page], is_array=True, pagination=pg)


@bp.route("/accounts/<id>/subscriptions/<sid>/addons/<aid>", methods=["DELETE"])
def remove_addon(id, sid, aid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    sa = db.subscription_addons.get(aid)
    if sa is None or sa["subscription_id"] != sid:
        raise errors.not_found("Subscription add-on not found")
    if sa["status"] != "ACTIVE":
        raise errors.invalid_state("Add-on is not ACTIVE")

    sa["status"] = "REMOVED"
    touch(sa)
    # A child fact (add-on set) changed, so the subscription's derived MRR and
    # its updated_at/version refresh in the same operation (PRD §2.9).
    touch(sub)
    billing.reconcile_subscription_and_account(sub)
    return success(S.ser_subscription_addon(sa))


# =============================================================================
# Pause windows (PRD §3.9)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions/<sid>/pause-windows", methods=["POST"])
def add_pause_window(id, sid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    body = V.get_body()
    pf_raw = V.require_str(body, "pause_from")
    pt_raw = V.require_str(body, "pause_to")
    pause_from = parse_dt(pf_raw)
    pause_to = parse_dt(pt_raw)
    if not (pause_from < pause_to):
        raise errors.invalid_request("pause_from must be strictly earlier than pause_to")

    # Buffered-gap conflict (priority 16): [pause_from - 7d, pause_to + 7d)
    # intersects an existing SCHEDULED window -> ERR_PAUSE_WINDOW_CONFLICT.
    buf_from = add_days(pause_from, -MIN_PAUSE_GAP_DAYS)
    buf_to = add_days(pause_to, MIN_PAUSE_GAP_DAYS)
    for w in db.pause_windows.values():
        if w["subscription_id"] != sid or w["status"] != "SCHEDULED":
            continue
        if buf_from < w["pause_to"] and w["pause_from"] < buf_to:
            raise errors.ApiError(errors.ERR_PAUSE_WINDOW_CONFLICT, 409,
                                  "Pause window conflicts with an existing scheduled window")

    w = {
        "subscription_id": sid,
        "pause_from": pause_from,
        "pause_to": pause_to,
        "status": "SCHEDULED",
    }
    stamp_new(w)
    db.pause_windows[w["id"]] = w
    return success(S.ser_pause_window(w), status=201)


@bp.route("/subscriptions/<id>/pause-windows", methods=["GET"])
def list_pause_windows(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    sub = db.subscriptions.get(id)
    if sub is None:
        raise errors.not_found("Subscription not found")
    require_account_owner_match(role, user_id, sub["account_id"])
    limit, offset = parse_pagination()
    items = [w for w in db.pause_windows.values() if w["subscription_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_pause_window(w) for w in page], is_array=True, pagination=pg)


@bp.route("/accounts/<id>/subscriptions/<sid>/pause-windows/<pwid>", methods=["DELETE"])
def cancel_pause_window(id, sid, pwid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    w = db.pause_windows.get(pwid)
    if w is None or w["subscription_id"] != sid:
        raise errors.not_found("Pause window not found")
    if w["status"] != "SCHEDULED":
        raise errors.invalid_state("Pause window is not SCHEDULED")
    w["status"] = "CANCELED"
    touch(w)
    return success(S.ser_pause_window(w))


# =============================================================================
# Usage metering (PRD §3.4)
# =============================================================================
@bp.route("/accounts/<id>/subscriptions/<sid>/usage", methods=["POST"])
def record_usage(id, sid):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner", "BillingAdmin"})
    account, sub = _get_sub_under_account(id, sid)
    require_account_owner_match(role, user_id, id)

    body = V.get_body()
    units = V.require_int(body, "units", minimum=1)  # units > 0
    recorded_at_raw = V.require_str(body, "recorded_at")
    recorded_at = parse_dt(recorded_at_raw)

    # Within current [period_start, period_end) (priority 12 -> ERR_USAGE_OUT_OF_PERIOD).
    if not (sub["period_start"] <= recorded_at < sub["period_end"]):
        raise errors.ApiError(errors.ERR_USAGE_OUT_OF_PERIOD, 409,
                              "recorded_at outside the current billing period")

    ur = {
        "subscription_id": sid,
        "units": units,
        "recorded_at": recorded_at,
        "billed": False,
    }
    # UsageRecord is lean: id + created_at only, no updated_at/version (PRD §2.4).
    stamp_new(ur, versioned=False)
    db.usage_records[ur["id"]] = ur
    return success(S.ser_usage_record(ur), status=201)


@bp.route("/subscriptions/<id>/usage", methods=["GET"])
def list_usage(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    sub = db.subscriptions.get(id)
    if sub is None:
        raise errors.not_found("Subscription not found")
    require_account_owner_match(role, user_id, sub["account_id"])
    limit, offset = parse_pagination()
    items = [u for u in db.usage_records.values() if u["subscription_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_usage_record(u) for u in page], is_array=True, pagination=pg)
