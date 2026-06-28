"""Subscription endpoints (PRD §3.4)."""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts
from clock import clock, parse_iso8601, floor_days_between
from helpers import (
    get_body, require_str, require_int, parse_pagination, sort_by_created,
    paginate, stamp_new, touch,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_subscription
from services.calculations import (
    BILLING_CYCLE_DAYS, provisional_remaining_cents, final_daily_floor_cents,
    upgrade_proration_cents,
)
from services.compute import (
    recompute_lifetime_paid, recompute_credit_balance,
    recompute_credit_balance_by_member_id,
)
from services.lookups import (
    get_member_or_404, get_subscription_or_404, ref_plan_or_404,
    require_member_ownership,
)

bp = Blueprint("subscriptions", __name__)

MAX_FREEZE_CYCLES = 3


def _append_invoice(subscription_id, kind, amount_cents):
    inv = {
        "id": new_id(),
        "created_at": now_ts(),
        "_seq": db.next_seq(),
        "subscription_id": subscription_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "PAID",
    }
    db.invoices[inv["id"]] = inv
    return inv


def _subscription_owner_check(sub):
    if g.user_role == "Member" and g.user_id != sub["member_id"]:
        raise errors.forbidden("A member may act only on their own subscription")


# --- Start subscription ---------------------------------------------------

@bp.post("/members/<member_id>/subscription")
@require_roles("Member", "LocationManager")
def start_subscription(member_id):
    member = get_member_or_404(member_id)
    require_member_ownership(member_id)
    body = get_body()
    plan_id = require_str(body, "plan_id")
    plan = ref_plan_or_404(plan_id)
    # Priority 11: a member may not start a new subscription while a non-CANCELLED
    # subscription exists.
    for s in db.subscriptions.values():
        if s["member_id"] == member_id and s["status"] != "CANCELLED":
            raise errors.ApiError(
                errors.ERR_DUPLICATE_SUBSCRIPTION, 409,
                "Member already has a live subscription")
    sub = stamp_new({
        "member_id": member_id,
        "plan_id": plan_id,
        "status": "ACTIVE",
        "cycle_anchor_at": now_ts(),
        "granted_credits_remaining": plan["monthly_credit_grant"],
        "freeze_cycles_remaining": 0,
        "lifetime_paid_cents": 0,
    })
    db.subscriptions[sub["id"]] = sub
    _append_invoice(sub["id"], "SIGNUP", plan["monthly_fee_cents"])
    recompute_lifetime_paid(sub)
    recompute_credit_balance(member)
    return success(serialize_subscription(sub), 201)


@bp.get("/subscriptions")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def list_subscriptions():
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    items = list(db.subscriptions.values())
    if g.user_role == "Member":
        items = [s for s in items if s["member_id"] == g.user_id]
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if plan_id is not None:
        items = [s for s in items if s["plan_id"] == plan_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success(
        [serialize_subscription(s) for s in page], limit, offset, total)


@bp.get("/subscriptions/<subscription_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def get_subscription(subscription_id):
    sub = get_subscription_or_404(subscription_id)
    if g.user_role == "Member" and g.user_id != sub["member_id"]:
        raise errors.forbidden("A member may act only on their own subscription")
    return success(serialize_subscription(sub), 200)


# --- Refund quote (non-mutating, dual-variant) ----------------------------

@bp.get("/subscriptions/<subscription_id>/refund-quote")
@require_roles("Member", "LocationManager")
def refund_quote(subscription_id):
    sub = get_subscription_or_404(subscription_id)
    _subscription_owner_check(sub)
    plan = db.membership_plans.get(sub["plan_id"])
    anchor = parse_iso8601(sub["cycle_anchor_at"])
    elapsed_days = floor_days_between(anchor, clock.now())
    remaining_days = BILLING_CYCLE_DAYS - elapsed_days
    return success({
        "provisional_remaining_cents": provisional_remaining_cents(
            plan["monthly_fee_cents"], remaining_days),
        "final_daily_floor_cents": final_daily_floor_cents(
            plan["monthly_fee_cents"], elapsed_days),
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
    }, 200)


# --- Upgrade (OCC-guarded) ------------------------------------------------

@bp.post("/subscriptions/<subscription_id>/upgrade")
@require_roles("Member", "LocationManager")
def upgrade_subscription(subscription_id):
    sub = get_subscription_or_404(subscription_id)
    _subscription_owner_check(sub)
    body = get_body()
    plan_id = require_str(body, "plan_id")
    expected_version = require_int(body, "expected_subscription_version")
    # Priority 4: body FK existence.
    new_plan = ref_plan_or_404(plan_id)
    # Priority 8: optimistic concurrency.
    if expected_version != sub["version"]:
        raise errors.stale_version("Stale subscription version")
    # Priority 9: state must be ACTIVE for upgrade.
    if sub["status"] != "ACTIVE":
        raise errors.invalid_state("Subscription is not ACTIVE")
    old_plan = db.membership_plans.get(sub["plan_id"])
    # Priority 19: upgrade direction (strictly greater fee).
    fee_delta = new_plan["monthly_fee_cents"] - old_plan["monthly_fee_cents"]
    if fee_delta <= 0:
        raise errors.ApiError(
            errors.ERR_NOT_AN_UPGRADE, 409,
            "Target plan fee must be strictly greater than current")
    # Load-bearing order: resolve days from CURRENT anchor BEFORE re-anchoring.
    anchor = parse_iso8601(sub["cycle_anchor_at"])
    elapsed_days = floor_days_between(anchor, clock.now())
    remaining_days = BILLING_CYCLE_DAYS - elapsed_days
    proration = upgrade_proration_cents(fee_delta, remaining_days)
    _append_invoice(sub["id"], "UPGRADE_PRORATION", proration)
    # Now re-anchor and switch the plan.
    sub["plan_id"] = plan_id
    sub["cycle_anchor_at"] = now_ts()
    sub["granted_credits_remaining"] = new_plan["monthly_credit_grant"]
    touch(sub)
    recompute_lifetime_paid(sub)
    recompute_credit_balance_by_member_id(sub["member_id"])
    return success(serialize_subscription(sub), 200)


# --- Freeze ---------------------------------------------------------------

def _has_booked_within_window(member_id, window_end_dt):
    """A member has a BOOKED booking whose starts_at falls within the frozen
    window [now, window_end)."""
    now = clock.now()
    for b in db.bookings.values():
        if b["member_id"] != member_id or b["status"] != "BOOKED":
            continue
        starts = parse_iso8601(b["starts_at"])
        if now <= starts < window_end_dt:
            return True
    return False


@bp.post("/subscriptions/<subscription_id>/freeze")
@require_roles("Member", "LocationManager")
def freeze_subscription(subscription_id):
    sub = get_subscription_or_404(subscription_id)
    _subscription_owner_check(sub)
    body = get_body()
    # Priority 6 well-formedness then priority 7 freeze-cycles range.
    if "freeze_cycles" not in body or body["freeze_cycles"] is None:
        raise errors.invalid_request("Missing required field: freeze_cycles")
    fc = body["freeze_cycles"]
    if isinstance(fc, bool) or not isinstance(fc, int):
        raise errors.invalid_request("freeze_cycles must be an integer")
    if fc < 1 or fc > MAX_FREEZE_CYCLES:
        raise errors.freeze_cycles_invalid()
    # Priority 9: state must be ACTIVE.
    if sub["status"] != "ACTIVE":
        raise errors.invalid_state("Subscription is not ACTIVE")
    # No BOOKED booking within the frozen window (fc cycles of 30 days each).
    from clock import add_days
    anchor = parse_iso8601(sub["cycle_anchor_at"])
    window_end = add_days(anchor, BILLING_CYCLE_DAYS * fc)
    if _has_booked_within_window(sub["member_id"], window_end):
        raise errors.invalid_state(
            "Member has a BOOKED booking within the frozen window")
    sub["status"] = "FROZEN"
    sub["freeze_cycles_remaining"] = fc
    sub["granted_credits_remaining"] = 0
    touch(sub)
    recompute_credit_balance_by_member_id(sub["member_id"])
    return success(serialize_subscription(sub), 200)


# --- Unfreeze -------------------------------------------------------------

@bp.post("/subscriptions/<subscription_id>/unfreeze")
@require_roles("Member", "LocationManager")
def unfreeze_subscription(subscription_id):
    sub = get_subscription_or_404(subscription_id)
    _subscription_owner_check(sub)
    if sub["status"] != "FROZEN":
        raise errors.invalid_state("Subscription is not FROZEN")
    plan = db.membership_plans.get(sub["plan_id"])
    sub["status"] = "ACTIVE"
    sub["freeze_cycles_remaining"] = 0
    sub["cycle_anchor_at"] = now_ts()
    sub["granted_credits_remaining"] = plan["monthly_credit_grant"]
    touch(sub)
    recompute_credit_balance_by_member_id(sub["member_id"])
    return success(serialize_subscription(sub), 200)


# --- Cancel ---------------------------------------------------------------

@bp.post("/subscriptions/<subscription_id>/cancel")
@require_roles("Member", "LocationManager")
def cancel_subscription(subscription_id):
    sub = get_subscription_or_404(subscription_id)
    _subscription_owner_check(sub)
    if sub["status"] not in ("ACTIVE", "FROZEN"):
        raise errors.invalid_state("Subscription is not in a live state")
    if sub["status"] == "ACTIVE":
        sub["granted_credits_remaining"] = 0
    else:  # FROZEN
        sub["freeze_cycles_remaining"] = 0
    sub["status"] = "CANCELLED"
    touch(sub)
    recompute_credit_balance_by_member_id(sub["member_id"])
    return success(serialize_subscription(sub), 200)
