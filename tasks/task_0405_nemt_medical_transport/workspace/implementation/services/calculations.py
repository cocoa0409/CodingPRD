"""Calculation rules (scaffold 1.3 / PRD 3.4, 3.7, 3.8, 3.9).

All money is integer cents; rounding is round-half-up. The *point* of rounding
differs between the two cost variants and is the engine of reconciliation
variance:
  - claimed_cost_forward: sum-then-round ONCE at the end.
  - encounter_cost_chronological: round EACH leg, then sum.
"""
from db import db, get_county_distance
from helpers import round_half_up

VARIANCE_TOLERANCE_CENTS = 500
NOSHOW_SUSPEND_THRESHOLD = 3


def rate_for_modality(modality):
    for rs in db.rate_schedules.values():
        if rs["modality"] == modality:
            return rs
    return None


def claimed_cost_forward(trip):
    """Forward variant from the intake estimate (PRD 3.7).

    leg_multiplier = 2 if round-trip else 1.
    base_component = base_fare_cents * leg_multiplier
    loaded_component = loaded_rate_cents_per_mile * scheduled_loaded_miles
    claimed = round_half_up(base_component + loaded_component * leg_multiplier)
    Dwell and odometer actuals are excluded.
    """
    rate = rate_for_modality(trip["modality"])
    leg_multiplier = 2 if trip["is_round_trip"] else 1
    base_component = rate["base_fare_cents"] * leg_multiplier
    loaded_component = rate["loaded_rate_cents_per_mile"] * trip["scheduled_loaded_miles"]
    return round_half_up(base_component + loaded_component * leg_multiplier)


def encounter_cost_chronological(trip):
    """Chronological variant from leg actuals (PRD 3.8).

    Only DROPPED_OFF legs; order by dropped_off_at ASC, tie-break created_at ASC.
    Each leg cost = round_half_up(base + loaded*odometer + dwell_rate*dwell_minutes).
    Sum the rounded per-leg amounts.
    """
    rate = rate_for_modality(trip["modality"])
    legs = [l for l in db.legs.values()
            if l["trip_id"] == trip["id"] and l["leg_status"] == "DROPPED_OFF"]
    legs.sort(key=lambda l: (l["dropped_off_at"], l["created_at"]))
    total = 0
    for leg in legs:
        leg_cents = round_half_up(
            rate["base_fare_cents"]
            + rate["loaded_rate_cents_per_mile"] * leg["odometer_loaded_miles"]
            + rate["dwell_cents_per_minute"] * leg["dwell_minutes"]
        )
        total += leg_cents
    return total


def deadhead(driver, member, broker):
    """Returns (raw_deadhead_miles, billable_charge_cents) (PRD 3.4).

    Billable accrues strictly above the broker free allowance ('>').
    """
    raw = get_county_distance(driver["base_county"], member["home_county"])
    if raw is None:
        raw = 0
    if raw > broker["free_deadhead_miles"]:
        billable = raw - broker["free_deadhead_miles"]
    else:
        billable = 0
    charge = round_half_up(billable * broker["deadhead_rate_cents_per_mile"])
    return raw, charge


def will_call_dwell_minutes(rate, ready_called_at, picked_up_at):
    """Floor elapsed to whole minutes, subtract free allowance with strict '>'
    boundary (PRD 3.8 / scaffold will_call_dwell)."""
    elapsed_seconds = (picked_up_at - ready_called_at).total_seconds()
    raw = int(elapsed_seconds // 60)  # floor to whole minutes
    if raw > rate["dwell_free_minutes"]:
        return raw - rate["dwell_free_minutes"]
    return 0


def reconciliation_variance(trip):
    """encounter_cost_cents - claimed_cost_cents (PRD 3.9)."""
    return trip["encounter_cost_cents"] - trip["claimed_cost_cents"]
