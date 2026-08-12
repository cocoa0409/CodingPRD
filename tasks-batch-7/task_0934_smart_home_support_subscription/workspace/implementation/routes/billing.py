"""Plans, subscriptions, tier changes and the billing cycle (PRD 3.2)."""

from flask import Blueprint, request

import serializers as S
from counters import recompute_overage_device_count
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from ladder import (begin, gates, household_subscription, in_force_subscription,
                    invalid_state, occ, plan_of, req_bool, req_enum, req_id,
                    req_int, req_str, resolve, scope_household, touch, opt_bool)
from money import BILLING_CYCLE_DAYS, as_decimal, clamp_days, round_half_up
from store import clock, db, new_row, sort_rows
from timeutil import add_days, floor_days_between, render_instant, try_parse_instant

bp = Blueprint("billing", __name__)
PREFIX = "/smart-home-support"

PLAN_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Owner", "BillingAdmin")


# --------------------------------------------------------------------------
# Subscription plans (configuration entity: no version, no updated_at)
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/subscription-plans")
def create_plan():
    ctx = begin(("PlatformAdmin",))
    body = ctx.body
    tier = req_enum(body, "tier")
    coverage_mode = req_enum(body, "coverage_mode")
    row = new_row(versioned=False)
    row.update({
        "tier": tier,
        "monthly_fee_cents": req_int(body, "monthly_fee_cents", 0),
        "included_device_count": req_int(body, "included_device_count", 1),
        "overage_fee_cents_per_device": req_int(body, "overage_fee_cents_per_device", 0),
        "coverage_mode": coverage_mode,
        "first_response_minutes_p1": req_int(body, "first_response_minutes_p1", 1),
        "first_response_minutes_p2": req_int(body, "first_response_minutes_p2", 1),
        "first_response_minutes_p3": req_int(body, "first_response_minutes_p3", 1),
        "onsite_resolution_hours_p1": req_int(body, "onsite_resolution_hours_p1", 1),
        "onsite_resolution_hours_p2": req_int(body, "onsite_resolution_hours_p2", 1),
        "onsite_resolution_hours_p3": req_int(body, "onsite_resolution_hours_p3", 1),
        "warranty_extension_months": req_int(body, "warranty_extension_months", 0),
        "included_install_credits": req_int(body, "included_install_credits", 0),
        "advance_replacement_eligible": req_bool(body, "advance_replacement_eligible"),
    })
    db.subscription_plans[row["id"]] = row
    return created(S.subscription_plan(row))


@bp.get(PREFIX + "/subscription-plans/<pid>")
def read_plan(pid):
    begin(PLAN_READ_ROLES)
    found = resolve(plan=pid)
    return ok(S.subscription_plan(found["plan"]))


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------
def _roll_window(sub, start_dt):
    sub["cycle_start_at"] = render_instant(start_dt)
    sub["cycle_end_at"] = render_instant(add_days(start_dt, BILLING_CYCLE_DAYS))


@bp.post(PREFIX + "/subscriptions")
def create_subscription():
    ctx = begin(("PlatformAdmin",))
    body = ctx.body
    found = resolve(household=body.get("household_id"), plan=body.get("plan_id"))
    household = found.get("household")
    plan = found.get("plan")
    if household is None:
        req_id(body, "household_id")
    if plan is None:
        req_id(body, "plan_id")
    allow_overage = opt_bool(body, "allow_overage", False)
    # Subscription creation is exempt from gate 4 (PRD 2.8), so a household
    # whose previous subscription was cancelled can be re-subscribed.
    gates(household=household, skip_subscription=True)

    existing = in_force_subscription(household["id"])
    if existing is not None:
        invalid_state("Exactly one non-CANCELLED subscription may exist per household.")

    now = clock.now()
    row = new_row()
    row.update({
        "household_id": household["id"],
        "plan_id": plan["id"],
        "pending_tier_plan_id": None,
        "status": "ACTIVE",
        "allow_overage": allow_overage,
        "cycle_index": 1,
        "monthly_fee_cents": plan["monthly_fee_cents"],
        "install_credits_granted": plan["included_install_credits"],
        "install_credits_consumed": 0,
        "install_credits_remaining": plan["included_install_credits"],
        "overage_device_count": 0,
        "overage_charges_cents_this_cycle": 0,
        "credits_issued_cents_this_cycle": 0,
        "next_invoice_credit_cents": 0,
        "next_invoice_adjustment_cents": 0,
    })
    _roll_window(row, now)
    db.subscriptions[row["id"]] = row
    recompute_overage_device_count(row)
    return created(S.subscription(row))


@bp.get(PREFIX + "/subscriptions")
def list_subscriptions():
    begin(PLAN_READ_ROLES)
    limit, offset = read_pagination(request.args)
    hid = request.args.get("household_id")
    plan_id = request.args.get("plan_id")
    pending = request.args.get("pending_tier_plan_id")
    rows = []
    for row in db.subscriptions.values():
        if hid is not None and row.get("household_id") != hid:
            continue
        if plan_id is not None and row.get("plan_id") != plan_id:
            continue
        if pending is not None and row.get("pending_tier_plan_id") != pending:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.subscription(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/subscriptions/<sid>")
def read_subscription(sid):
    ctx = begin(PLAN_READ_ROLES)
    found = resolve(subscription=sid)
    sub = found["subscription"]
    scope_household(ctx, sub.get("household_id"))
    return ok(S.subscription(sub))


@bp.post(PREFIX + "/subscriptions/<sid>/change-tier")
def change_tier(sid):
    ctx = begin(("BillingAdmin", "PlatformAdmin"))
    body = ctx.body
    found = resolve(plan=body.get("target_plan_id"), subscription=sid)
    target_plan = found.get("plan")
    sub = found["subscription"]
    if target_plan is None:
        req_id(body, "target_plan_id")
    household = db.households.get(sub.get("household_id"))
    scope_household(ctx, sub.get("household_id"))
    # Rung 22 -- optimistic concurrency on the parent Subscription row.
    occ(body, "expected_subscription_version", sub)
    gates(household=household)
    if sub.get("status") not in ("ACTIVE", "PAST_DUE", "SUSPENDED", "CANCEL_PENDING"):
        invalid_state("The subscription's status does not permit a tier change.")

    old_fee = sub["monthly_fee_cents"]
    new_fee = target_plan["monthly_fee_cents"]
    if new_fee > old_fee:
        # Upgrade: immediate, prorated on the whole days remaining in the cycle.
        cycle_end = try_parse_instant(sub["cycle_end_at"])
        days = clamp_days(floor_days_between(clock.now(), cycle_end))
        charge = round_half_up(as_decimal(new_fee - old_fee) * as_decimal(days)
                               / as_decimal(BILLING_CYCLE_DAYS))
        sub["plan_id"] = target_plan["id"]
        sub["monthly_fee_cents"] = new_fee
        sub["pending_tier_plan_id"] = None
        sub["next_invoice_adjustment_cents"] += charge
    else:
        # Downgrade: deferred to the next cycle close; nothing is charged and
        # plan_id / monthly_fee_cents are left exactly as they were.
        sub["pending_tier_plan_id"] = target_plan["id"]
    touch(sub)
    return ok(S.subscription(sub))


@bp.post(PREFIX + "/subscriptions/<sid>/set-overage-policy")
def set_overage_policy(sid):
    ctx = begin(("BillingAdmin", "PlatformAdmin"))
    found = resolve(subscription=sid)
    sub = found["subscription"]
    household = db.households.get(sub.get("household_id"))
    scope_household(ctx, sub.get("household_id"))
    allow_overage = req_bool(ctx.body, "allow_overage")
    gates(household=household)
    sub["allow_overage"] = allow_overage
    touch(sub)
    return ok(S.subscription(sub))


@bp.post(PREFIX + "/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    ctx = begin(("Owner", "PlatformAdmin"))
    found = resolve(subscription=sid)
    sub = found["subscription"]
    household = db.households.get(sub.get("household_id"))
    scope_household(ctx, sub.get("household_id"))
    gates(household=household)
    if sub.get("status") not in ("ACTIVE", "PAST_DUE"):
        invalid_state("Only an ACTIVE or PAST_DUE subscription may be cancelled.")
    sub["status"] = "CANCEL_PENDING"
    sub["pending_tier_plan_id"] = None
    touch(sub)
    return ok(S.subscription(sub))


@bp.post(PREFIX + "/subscriptions/<sid>/close-cycle")
def close_cycle(sid):
    ctx = begin(("PlatformAdmin",))
    found = resolve(subscription=sid)
    sub = found["subscription"]
    household = db.households.get(sub.get("household_id"))
    payment_outcome = req_enum(ctx.body, "payment_outcome")
    gates(household=household)

    status = sub.get("status")
    if status not in ("ACTIVE", "PAST_DUE", "SUSPENDED", "CANCEL_PENDING"):
        invalid_state("The subscription's status does not permit a cycle close.")

    # Adjudication of friction 2: READING B -- the endpoint-level contract
    # applies on EVERY hop and the per-hop itemised list states only the
    # hop-specific extras.  Reading A (the per-hop list is exhaustive) would
    # leave four PRD-declared effects unreachable on every hop -- the resets of
    # next_invoice_credit_cents and next_invoice_adjustment_cents are named
    # nowhere in the per-hop lists at all, and the recomputation of
    # install_credits_remaining and the application of pending_tier_plan_id are
    # named on one hop only -- so Reading B keeps the largest number of
    # declared behaviours reachable.  The single explicit per-hop NEGATIVE
    # ("No fresh install credits are granted on this hop") is determinate
    # prose rather than friction and is therefore honoured: the grant fires on
    # the three hops that land in ACTIVE and is withheld on the two FAILED
    # hops and on the cancellation hop.
    grant_credits = False
    if status == "ACTIVE" and payment_outcome == "SUCCEEDED":
        new_status = "ACTIVE"
        grant_credits = True
    elif status == "ACTIVE":
        new_status = "PAST_DUE"
    elif status == "PAST_DUE" and payment_outcome == "SUCCEEDED":
        new_status = "ACTIVE"
        grant_credits = True
    elif status == "PAST_DUE":
        new_status = "SUSPENDED"
    elif status == "SUSPENDED" and payment_outcome == "SUCCEEDED":
        new_status = "ACTIVE"
        grant_credits = True
    elif status == "SUSPENDED":
        invalid_state("A SUSPENDED subscription only advances on a SUCCEEDED payment.")
        new_status = status
    else:  # CANCEL_PENDING, with either payment_outcome
        new_status = "CANCELLED"

    # Endpoint-level contract, applied on every hop.
    prior_end = try_parse_instant(sub["cycle_end_at"])
    sub["cycle_index"] = (sub.get("cycle_index") or 0) + 1
    _roll_window(sub, prior_end)
    if grant_credits:
        plan = plan_of(sub)
        if plan is not None:
            sub["install_credits_granted"] += plan["included_install_credits"]
    pending = sub.get("pending_tier_plan_id")
    if pending:
        new_plan = db.subscription_plans.get(pending)
        if new_plan is not None:
            sub["plan_id"] = new_plan["id"]
            sub["monthly_fee_cents"] = new_plan["monthly_fee_cents"]
        sub["pending_tier_plan_id"] = None
    sub["install_credits_remaining"] = max(
        0, sub["install_credits_granted"] - sub["install_credits_consumed"])
    sub["credits_issued_cents_this_cycle"] = 0
    sub["overage_charges_cents_this_cycle"] = 0
    sub["next_invoice_credit_cents"] = 0
    sub["next_invoice_adjustment_cents"] = 0
    sub["status"] = new_status

    # The cascade onto Household.account_status.
    if status == "PAST_DUE" and new_status == "SUSPENDED" and household is not None:
        household["account_status"] = "SUSPENDED"
        household["suspended_at"] = clock.now_iso()
        touch(household)
    elif status == "SUSPENDED" and new_status == "ACTIVE" and household is not None:
        household["account_status"] = "ACTIVE"
        household["suspended_at"] = None
        touch(household)

    touch(sub)
    return ok(S.subscription(sub))
