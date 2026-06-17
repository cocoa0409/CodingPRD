"""Calculation rules (PRD §3.2, §3.4, §3.5, §3.6, §3.7; SCAFFOLD §1.3).

All money is integer cents; each rounding step rounds half up in the pinned
order the PRD specifies (PRD §2.7).
"""
from helpers import ceil_hours, floor_minutes, round_half_up

# Cancellation tier constants (SCAFFOLD calc cancellation_tier).
TIER1_LEAD_MIN = 60
TIER1_PCT = 25
TIER2_PCT = 50

# Flight delay threshold in minutes (SCAFFOLD calc flight_delay_propagation).
FLIGHT_DELAY_THRESHOLD_MIN = 15


def fare_base_cents(reservation, vehicle_class):
    """Fare base, identical for estimate / final / payout (PRD §3.2, §3.4, §3.5).

    HOURLY: ceil(charter_hours) * hourly_rate_cents.
    Otherwise: base_fare_cents + round(per_mile_cents * estimated_miles).
    """
    if reservation["trip_type"] == "HOURLY":
        billable_hours = ceil_hours(reservation["charter_hours"])
        return vehicle_class["hourly_rate_cents"] * billable_hours
    miles_product = round_half_up(vehicle_class["per_mile_cents"] * reservation["estimated_miles"])
    return vehicle_class["base_fare_cents"] + miles_product


def effective_gratuity_pct(reservation, account):
    """gratuity_pct_override when present, else account default (PRD §3.2)."""
    override = reservation.get("gratuity_pct_override")
    if override is not None:
        return override
    return account["default_gratuity_pct"]


def estimate_quote(reservation, vehicle_class, account):
    """Forward-looking estimate; no wait charge (PRD §3.2).

    Pinned order: fare_base -> discount -> gratuity (on discounted base) -> + tolls.
    Returns (total, discounted_base, gratuity).
    """
    fare_base = fare_base_cents(reservation, vehicle_class)
    discount_pct = account["negotiated_discount_pct"]
    discounted_base = round_half_up(fare_base * (100 - discount_pct) / 100)
    gratuity_pct = effective_gratuity_pct(reservation, account)
    gratuity = round_half_up(discounted_base * gratuity_pct / 100)
    total = discounted_base + gratuity + reservation["tolls_cents"]
    return total, discounted_base, gratuity


def final_settlement(reservation, vehicle_class, account):
    """Final settlement; actual wait folded into base BEFORE discount/gratuity (PRD §3.4).

    Returns final_total_cents.
    """
    fare_base = fare_base_cents(reservation, vehicle_class)
    wait_charge = reservation["chargeable_wait_minutes"] * vehicle_class["wait_per_minute_cents"]
    pre_discount = fare_base + wait_charge
    discount_pct = account["negotiated_discount_pct"]
    discounted_base = round_half_up(pre_discount * (100 - discount_pct) / 100)
    gratuity_pct = effective_gratuity_pct(reservation, account)
    gratuity = round_half_up(discounted_base * gratuity_pct / 100)
    return discounted_base + gratuity + reservation["tolls_cents"]


def wait_time(arrived_at, boarded_at, vehicle_class):
    """Chargeable wait minutes beyond the grace (PRD §3.4).

    raw = floor((boarded - arrived) / 60); chargeable = max(0, raw - grace).
    """
    raw = floor_minutes(boarded_at, arrived_at)
    grace = vehicle_class["included_wait_minutes"]
    return max(0, raw - grace)


def affiliate_payout(reservation, vehicle_class, affiliate):
    """Operator-side payout on raw fare base (PRD §3.5).

    round(fare_base * payout_share_pct / 100). No wait/discount/gratuity/tolls.
    """
    fare_base = fare_base_cents(reservation, vehicle_class)
    return round_half_up(fare_base * affiliate["payout_share_pct"] / 100)


def cancellation_tier(reservation, account, now_dt):
    """Lead-time tier and fee (PRD §3.7).

    penalty_base = estimate discounted base (quote total - gratuity - tolls), 0 if
    never quoted. Returns (tier, lead_minutes, fee_cents).
    """
    from helpers import parse_dt

    pickup = parse_dt(reservation["pickup_at"], "pickup_at")
    lead_minutes = floor_minutes(pickup, now_dt)
    grace = account["cancellation_grace_minutes"]

    penalty_base = reservation.get("_estimate_discounted_base")
    if penalty_base is None:
        penalty_base = 0

    if lead_minutes >= grace:
        return "FREE", lead_minutes, 0
    if lead_minutes >= TIER1_LEAD_MIN:
        return "TIER1", lead_minutes, round_half_up(penalty_base * TIER1_PCT / 100)
    if lead_minutes >= 0:
        return "TIER2", lead_minutes, round_half_up(penalty_base * TIER2_PCT / 100)
    return "NO_SHOW", lead_minutes, penalty_base
