"""Calculation rules (SCAFFOLD §1.3, PRD §3).

All money is integer cents. The only rounding decision is the loyalty discount
inside the quoted estimate (round half-up once at the end). Decimal + ROUND_HALF_UP
is used there to avoid float error.
"""
import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import db
from util import parse_iso8601

# ---- constants (verbatim from scaffold) ----------------------------------
WEEKLY_BREAKPOINT_DAYS = 7
YOUNG_DRIVER_AGE_THRESHOLD = 25
FUEL_PER_EIGHTH_CENTS = 1500
MINOR_DEDUCTIBLE_CENTS = 25000
MAJOR_DEDUCTIBLE_CENTS = 100000
TOTAL_DEDUCTIBLE_CENTS = 250000
NO_LDW_CEILING_CENTS = 5000000
POINTS_DIVISOR_CENTS = 100
SILVER_THRESHOLD_POINTS = 500
GOLD_THRESHOLD_POINTS = 2000
NO_SHOW_GRACE_MINUTES = 120
NO_SHOW_STRIKE_LIMIT = 3


def loyalty_discount_pct(tier):
    if tier == "GOLD":
        return Decimal("0.10")
    if tier == "SILVER":
        return Decimal("0.05")
    return Decimal("0.00")


def tier_multiplier(tier):
    if tier == "GOLD":
        return 3
    if tier == "SILVER":
        return 2
    return 1


def member_tier(lifetime_points):
    """Tier as a pure function of lifetime_points; lower edge inclusive (>=)."""
    if lifetime_points >= GOLD_THRESHOLD_POINTS:
        return "GOLD"
    if lifetime_points >= SILVER_THRESHOLD_POINTS:
        return "SILVER"
    return "STANDARD"


def compute_rental_days(pickup_at_iso, dropoff_at_iso):
    """ceil((dropoff - pickup) / 24h), floor of 1."""
    pickup = parse_iso8601(pickup_at_iso)
    dropoff = parse_iso8601(dropoff_at_iso)
    delta_seconds = (dropoff - pickup).total_seconds()
    days = math.ceil(delta_seconds / 86400.0)
    return max(1, days)


def select_rate_plan(pickup_location_id, class_id, pickup_at_iso):
    """Active plan with latest effective_from <= pickup_at; tie-break created_at ASC."""
    pickup = parse_iso8601(pickup_at_iso)
    candidates = []
    for p in db.rate_plans.values():
        if not p["active"]:
            continue
        if p["location_id"] != pickup_location_id:
            continue
        if p["class_id"] != class_id:
            continue
        eff = parse_iso8601(p["effective_from"])
        if eff <= pickup:
            candidates.append((eff, p))
    if not candidates:
        return None
    # rank by effective_from DESC, then created_at ASC (via _seq which is
    # monotonic with creation order).
    candidates.sort(key=lambda ep: (-ep[0].timestamp(), ep[1]["_seq"]))
    return candidates[0][1]


def quote_components(reservation):
    """Return the component breakdown used by both the quoted estimate and the
    provisional settlement ledger lines.

    Components (all integer cents):
      base, addons, young, drop, discount
    quoted_total = base + addons + young + drop - discount
    """
    member = db.members[reservation["member_id"]]
    pickup_loc = db.locations[reservation["pickup_location_id"]]
    dropoff_loc = db.locations[reservation["dropoff_location_id"]]
    vclass = db.vehicle_classes[reservation["class_id"]]
    rental_days = reservation["rental_days"]

    plan = select_rate_plan(
        reservation["pickup_location_id"],
        reservation["class_id"],
        reservation["pickup_at"],
    )
    daily = plan["daily_rate_cents"] if plan else vclass["daily_rate_cents"]
    weekly = plan["weekly_rate_cents"] if plan else vclass["weekly_rate_cents"]

    if rental_days >= WEEKLY_BREAKPOINT_DAYS:
        whole_weeks = rental_days // 7
        leftover_days = rental_days % 7
        base = whole_weeks * weekly + leftover_days * daily
    else:
        base = rental_days * daily

    addons = rental_days * (
        (vclass["ldw_per_day_cents"] if reservation["ldw_selected"] else 0)
        + (vclass["pai_per_day_cents"] if reservation["pai_selected"] else 0)
    )

    if member["driver_age"] < YOUNG_DRIVER_AGE_THRESHOLD:
        young = rental_days * pickup_loc["young_driver_surcharge_per_day_cents"]
    else:
        young = 0

    if reservation["dropoff_location_id"] != reservation["pickup_location_id"]:
        drop = dropoff_loc["one_way_drop_fee_cents"]
    else:
        drop = 0

    pct = loyalty_discount_pct(member["tier"])
    if pct == Decimal("0.00"):
        discount = 0
    else:
        discount = int((Decimal(base) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return {
        "base": base,
        "addons": addons,
        "young": young,
        "drop": drop,
        "discount": discount,
    }


def reservation_quote(reservation):
    c = quote_components(reservation)
    return c["base"] + c["addons"] + c["young"] + c["drop"] - c["discount"]


def incident_liability(severity, assessed_damage_cents, ldw_in_effect):
    """Tiered cap on member exposure (SCAFFOLD incident_liability)."""
    if severity == "MINOR":
        base_cap = MINOR_DEDUCTIBLE_CENTS
    elif severity == "MAJOR":
        base_cap = MAJOR_DEDUCTIBLE_CENTS
    else:  # TOTAL
        base_cap = TOTAL_DEDUCTIBLE_CENTS
    if ldw_in_effect:
        return min(assessed_damage_cents, base_cap)
    return min(assessed_damage_cents, NO_LDW_CEILING_CENTS)


def loyalty_points_earned(final_total_cents, tier, half_rate):
    """floor(max(0, final)/100) * tier_mult; write-off pays floor(earned/2)."""
    base = max(0, final_total_cents)
    earned = (base // POINTS_DIVISOR_CENTS) * tier_multiplier(tier)
    if half_rate:
        return earned // 2
    return earned
