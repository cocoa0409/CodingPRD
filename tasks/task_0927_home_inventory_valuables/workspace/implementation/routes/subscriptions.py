"""The subscription's two independent axes (PRD 3.2)."""

import calc
import derive
import serializers
import store
from constants import (
    BILLING_OUTCOMES,
    BILLING_PERIOD_DAYS,
    PAST_DUE_GRACE_DAYS,
    PRORATION_MODES,
    REFRESH_INTERVAL_DAYS,
    SUBSCRIPTION_TIER_NAMES,
    SUBSCRIPTION_TIERS,
    TRIAL_DAYS,
)
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one
from timeutil import add_days, clock


def _sub(ctx):
    return ctx.row("subscription_id")


def _household(ctx):
    return store.households.get(_sub(ctx)["household_id"])


def _sub_household_id(ctx):
    return _sub(ctx)["household_id"]


def _reset_period(sub):
    derive.stamp(sub, "period_start_at", clock.now)
    derive.stamp(sub, "period_end_at", add_days(clock.now, BILLING_PERIOD_DAYS))
    sub["appraisal_credits_remaining"] = SUBSCRIPTION_TIERS[sub["tier"]]["included_appraisal_credits"]
    sub["packages_used_this_period"] = 0


# ---------------------------------------------------------------- creation
@endpoint(
    "POST",
    "/vault/subscriptions",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={"household_id": ("string", True), "tier": ("string", True)},
    enums={"tier": SUBSCRIPTION_TIER_NAMES},
    fks=("household_id",),
    household=lambda ctx: ctx.body.get("household_id"),
)
def create_subscription(ctx):
    tier = ctx.body["tier"]
    row = store.new_row(
        store.subscriptions,
        household_id=ctx.body["household_id"],
        tier=tier,
        status="TRIAL",
        refresh_state="CURRENT",
        appraisal_credits_remaining=SUBSCRIPTION_TIERS[tier]["included_appraisal_credits"],
        packages_used_this_period=0,
        monthly_fee_cents=SUBSCRIPTION_TIERS[tier]["monthly_fee_cents"],
        last_proration_charge_cents=0,
    )
    derive.stamp(row, "period_start_at", clock.now)
    derive.stamp(row, "period_end_at", add_days(clock.now, BILLING_PERIOD_DAYS))
    derive.stamp(row, "past_due_since_at", None)
    derive.stamp(row, "last_attested_at", None)
    derive.stamp(row, "refresh_due_at", add_days(row["_created_dt"], REFRESH_INTERVAL_DAYS))
    return one(serializers.subscription(row), 201)


@endpoint(
    "GET",
    "/vault/subscriptions/{subscription_id}",
    roles=["Homeowner", "HouseholdMember", "PlatformAdmin"],
    scope_household=_sub_household_id,
)
def read_subscription(ctx):
    return one(serializers.subscription(_sub(ctx)))


@endpoint("GET", "/vault/subscriptions", roles=["Homeowner", "HouseholdMember", "PlatformAdmin"])
def list_subscriptions(ctx):
    return list_response(
        store.all_of(store.subscriptions),
        ctx.args,
        serializers.subscription,
        {
            "household_id": field("household_id"),
            "status": field("status"),
            "refresh_state": field("refresh_state"),
        },
    )


# ------------------------------------------------------------ billing axis
def billing_target(sub, outcome):
    """The declared origin/outcome pairs of the status axis, with their timing
    preconditions.  Returns the target status or None."""
    status = sub["status"]
    if status == "TRIAL" and outcome == "PAYMENT_SUCCEEDED":
        return "ACTIVE"
    if status == "TRIAL" and outcome == "LAPSE":
        if clock.now >= add_days(sub["_created_dt"], TRIAL_DAYS):
            return "LAPSED"
        return None
    if status == "ACTIVE" and outcome == "PAYMENT_FAILED":
        return "PAST_DUE"
    if status == "PAST_DUE" and outcome == "PAYMENT_SUCCEEDED":
        return "ACTIVE"
    if status == "PAST_DUE" and outcome == "LAPSE":
        since = sub.get("_past_due_since_at_dt")
        if since is not None and clock.now >= add_days(since, PAST_DUE_GRACE_DAYS):
            return "LAPSED"
        return None
    if status == "LAPSED" and outcome == "CLOSE":
        return "CLOSED"
    return None


def _billing_rung13(ctx):
    if _sub(ctx)["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _billing_rung14(ctx):
    if billing_target(_sub(ctx), ctx.body["outcome"]) is None:
        raise ApiError("ERR_INVALID_STATE")


def lapse_cascade(household):
    """Hops 2-4: the write gate closes, FULL-redaction grants are voided, and
    active_share_count is recomputed."""
    if household is None:
        return
    grants = [
        g
        for g in store.all_of(store.share_grants)
        if g["household_id"] == household["id"] and g["status"] == "ACTIVE" and g["redaction_level"] == "FULL"
    ]
    derive.void_grants(grants, "SUBSCRIPTION_LAPSED")
    derive.recompute_write_gate(household, bump=True)
    derive.recompute_household(household, bump=True)


@endpoint(
    "POST",
    "/vault/subscriptions/{subscription_id}/billing-event",
    roles=["PlatformAdmin"],
    mutating=True,
    body={"outcome": ("string", True)},
    enums={"outcome": BILLING_OUTCOMES},
    household=_sub_household_id,
    rungs={13: _billing_rung13, 14: _billing_rung14},
)
def billing_event(ctx):
    sub = _sub(ctx)
    household = _household(ctx)
    target = billing_target(sub, ctx.body["outcome"])
    sub["status"] = target
    if target == "ACTIVE":
        derive.stamp(sub, "past_due_since_at", None)
        _reset_period(sub)
    elif target == "PAST_DUE":
        derive.stamp(sub, "past_due_since_at", clock.now)
    store.touch(sub)
    if target == "LAPSED":
        lapse_cascade(household)
    elif household is not None:
        derive.recompute_write_gate(household, bump=True)
    return one(serializers.subscription(sub))


# --------------------------------------------------------------- tier change
def _tier_rung13(ctx):
    if _sub(ctx)["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _tier_rung14(ctx):
    if ctx.body["tier"] == _sub(ctx)["tier"]:
        raise ApiError("ERR_INVALID_STATE")


def _usage_blocks(household_id, tier):
    limits = SUBSCRIPTION_TIERS[tier]
    item_usage, asset_usage, bytes_usage = calc.quota_usage(household_id)
    return (
        limits["max_items"] < item_usage
        or limits["max_assets"] < asset_usage
        or limits["max_asset_bytes"] < bytes_usage
    )


def _tier_rung33(ctx):
    if _usage_blocks(_sub(ctx)["household_id"], ctx.body["tier"]):
        raise ApiError("ERR_DOWNGRADE_BLOCKED_BY_USAGE")


@endpoint(
    "POST",
    "/vault/subscriptions/{subscription_id}/change-tier",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={
        "tier": ("string", True),
        "expected_subscription_version": ("integer", True),
        "proration_mode": ("string", False),
    },
    enums={"tier": SUBSCRIPTION_TIER_NAMES, "proration_mode": PRORATION_MODES},
    household=_sub_household_id,
    scope_household=_sub_household_id,
    rungs={13: _tier_rung13, 14: _tier_rung14, 33: _tier_rung33},
    occ=("expected_subscription_version", "ERR_STALE_SUBSCRIPTION_VERSION", _sub),
)
def change_tier(ctx):
    sub = _sub(ctx)
    new_tier = ctx.body["tier"]
    mode = ctx.body.get("proration_mode") or "DAILY"
    sub["last_proration_charge_cents"] = calc.proration(sub, new_tier, mode)
    sub["tier"] = new_tier
    sub["monthly_fee_cents"] = SUBSCRIPTION_TIERS[new_tier]["monthly_fee_cents"]
    sub["appraisal_credits_remaining"] = min(
        sub["appraisal_credits_remaining"], SUBSCRIPTION_TIERS[new_tier]["included_appraisal_credits"]
    )
    store.touch(sub)
    return one(serializers.subscription(sub))


# ------------------------------------------------------------ refresh axis
def _attest_rung14(ctx):
    if _sub(ctx)["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/subscriptions/{subscription_id}/attest-refresh",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={"attestation_note": ("string", False)},
    household=_sub_household_id,
    scope_household=_sub_household_id,
    rungs={14: _attest_rung14},
)
def attest_refresh(ctx):
    sub = _sub(ctx)
    derive.stamp(sub, "last_attested_at", clock.now)
    derive.stamp(sub, "refresh_due_at", add_days(clock.now, REFRESH_INTERVAL_DAYS))
    sub["refresh_state"] = "CURRENT"
    store.touch(sub)
    household = _household(ctx)
    if household is not None:
        derive.recompute_write_gate(household, bump=True)
    return one(serializers.subscription(sub))


# ------------------------------------------------------------ reinstatement
def _reinstate_rung13(ctx):
    if _sub(ctx)["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _reinstate_rung14(ctx):
    if _sub(ctx)["status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE")


def _reinstate_rung33(ctx):
    sub = _sub(ctx)
    if _usage_blocks(sub["household_id"], sub["tier"]):
        raise ApiError("ERR_DOWNGRADE_BLOCKED_BY_USAGE")


@endpoint(
    "POST",
    "/vault/subscriptions/{subscription_id}/reinstate",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    household=_sub_household_id,
    scope_household=_sub_household_id,
    rungs={13: _reinstate_rung13, 14: _reinstate_rung14, 33: _reinstate_rung33},
)
def reinstate(ctx):
    sub = _sub(ctx)
    sub["status"] = "ACTIVE"
    derive.stamp(sub, "past_due_since_at", None)
    _reset_period(sub)
    store.touch(sub)
    household = _household(ctx)
    if household is not None:
        derive.recompute_write_gate(household, bump=True)
    return one(serializers.subscription(sub))
