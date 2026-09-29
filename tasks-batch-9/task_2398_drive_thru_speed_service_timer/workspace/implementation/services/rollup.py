"""The pinned store rollup chain (PRD §2.7) plus its two helper calculations."""

from decimal import Decimal

from constants import (
    ACCURACY_HOLD_THRESHOLD,
    DUAL_PARALLEL_BUMP_CPH,
    MAX_OOT_COUNT,
    OOT_POSITIONS,
    TRAILING_WINDOW_SECONDS,
)
from db import db, dec, rhu, shift, touch
from errors import fail

ZERO = Decimal("0")


# --------------------------------------------------------------- band lookups
def policies_ordered():
    return sorted(db.tier_policies.values(), key=lambda row: row["created_at"])


def lookup_band(value):
    """Floor inclusive, ceiling exclusive, null ceiling unbounded (PRD §2.8)."""
    target = dec(value)
    for policy in policies_ordered():
        floor = dec(policy["cars_per_hour_floor"])
        ceiling = policy["cars_per_hour_ceiling"]
        if target >= floor and (ceiling is None or target < dec(ceiling)):
            return policy
    fail("ERR_TIER_POLICY_INCOMPLETE",
         "no volume-tier band contains a car rate of %s" % target)


def policy_for_tier(tier):
    for policy in policies_ordered():
        if policy["tier"] == tier:
            return policy
    fail("ERR_TIER_POLICY_INCOMPLETE", "no volume-tier band declared for %s" % tier)


# ------------------------------------------------------ active_override_selection
def active_override(restaurant_id, at):
    candidates = [
        row for row in db.forecast_overrides.values()
        if row["restaurant_id"] == restaurant_id
        and row["fo_state"] == "APPLIED"
        and row["effective_start_at"] <= at <= row["effective_end_at"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-dec(row["projected_cars_delta_pct"]), row["created_at"]))
    return candidates[0]


# ------------------------------------------------------------------- car rates
def trailing_closed_count(restaurant, extra=0):
    floor_instant = shift(db.clock, -TRAILING_WINDOW_SECONDS)
    total = 0
    for loop in db.timer_loops.values():
        if loop["restaurant_id"] != restaurant["id"]:
            continue
        if loop["timing_state"] != "CLOSED" or loop["depart_at"] is None:
            continue
        if floor_instant < loop["depart_at"] <= db.clock:
            total += 1
    return total + extra


def car_rates(restaurant, closed_count):
    observed = rhu(dec(closed_count) * 3600 / dec(TRAILING_WINDOW_SECONDS), 1)
    effective = observed
    if restaurant["staffing_basis"] == "FORECAST_ADJUSTED":
        override = active_override(restaurant["id"], db.clock)
        if override is not None:
            effective = rhu(observed * (Decimal(1) + dec(override["projected_cars_delta_pct"])), 1)
    return observed, effective


def preflight_tier(restaurant, extra_closed=0):
    """Prove the band table covers the rate the pending mutation will produce."""
    _observed, effective = car_rates(restaurant, trailing_closed_count(restaurant, extra_closed))
    lookup_band(effective)


# -------------------------------------------------------------- oot_requirement
def oot_requirement(restaurant, band, effective_rate, open_remake_count):
    lane_bump = 1 if (restaurant["lane_config"] == "DUAL_PARALLEL"
                      and dec(effective_rate) >= DUAL_PARALLEL_BUMP_CPH) else 0
    accuracy_bump = 1 if open_remake_count >= 1 else 0
    return min(MAX_OOT_COUNT, band["min_oot_count"] + lane_bump + accuracy_bump)


# --------------------------------------------------- restaurant_rollup_recompute
def recompute(restaurant, explicit=False):
    """Steps 1-9, exactly once each, in order. Nothing is written until step 4
    has successfully selected a band, so ERR_TIER_POLICY_INCOMPLETE aborts the
    whole request without a partial rollup."""
    rid = restaurant["id"]

    # 1 + 2 + 3
    closed_count = trailing_closed_count(restaurant)
    observed, effective = car_rates(restaurant, closed_count)

    # 4
    band = lookup_band(effective)

    # 5
    deployed_oot = 0
    committed = 0
    for row in db.deployments.values():
        if row["restaurant_id"] != rid:
            continue
        if row["deployment_state"] == "ACTIVE":
            committed += row["planned_minutes"]
            if row["position"] in OOT_POSITIONS:
                deployed_oot += 1
        elif row["deployment_state"] == "RELEASED":
            committed += row["labor_minutes_charged"]

    # 6 + part of 8
    open_remake = 0
    accrued = 0
    for row in db.accuracy_incidents.values():
        if row["restaurant_id"] != rid:
            continue
        if row["incident_state"] in ("LOGGED", "REMADE"):
            open_remake += 1
        if row["settlement_state"] in ("ACCRUED", "CHARGED"):
            accrued += row["remake_cost_cents"]

    # 7
    required_oot = oot_requirement(restaurant, band, effective, open_remake)

    # 8
    occupied = 0
    for row in db.merge_slots.values():
        if row["restaurant_id"] == rid and row["slot_state"] in ("RESERVED", "COMMITTED"):
            occupied += 1
    free = restaurant["merge_slots_capacity"] - occupied
    available = restaurant["labor_minutes_budget"] - committed

    # 9
    if restaurant["posture_override"] == "FROZEN":
        posture = "FROZEN"
    elif open_remake >= ACCURACY_HOLD_THRESHOLD:
        posture = "ACCURACY_HOLD"
    elif required_oot > deployed_oot:
        posture = "SURGE"
    else:
        posture = "OPEN"

    previous_posture = restaurant["service_posture"]

    restaurant["cars_closed_trailing"] = closed_count
    restaurant["cars_per_hour_observed"] = observed
    restaurant["cars_per_hour_effective"] = effective
    restaurant["volume_tier"] = band["tier"]
    restaurant["deployed_oot_count"] = deployed_oot
    restaurant["open_remake_count"] = open_remake
    restaurant["required_oot_count"] = required_oot
    restaurant["merge_slots_free"] = free
    restaurant["labor_minutes_committed"] = committed
    restaurant["labor_minutes_available"] = available
    restaurant["remake_cost_accrued_cents"] = accrued
    restaurant["service_posture"] = posture

    if explicit:
        # The five explicit store operations increment version by exactly 1.
        restaurant["updated_at"] = db.clock
        restaurant["version"] = restaurant["version"] + 1
    elif posture != previous_posture:
        # A system-driven posture reconciliation is itself a store mutation.
        touch(restaurant)

    return restaurant


def recompute_all():
    for restaurant in list(db.restaurants.values()):
        recompute(restaurant)
