"""Pricing & settlement calculations (PRD 2.7, 3.4, 3.6, 3.8, 3.11; scaffold 1.3).

Money is integer cents. round_half_up to whole cents via Decimal. Never float
arithmetic for money.
"""
from decimal import Decimal, ROUND_HALF_UP

import clock
from timeutil import parse_date, floor_days_between
from constants import (
    DEMAND_TIER_MID, DEMAND_TIER_HIGH, DEMAND_MULT_LOW, DEMAND_MULT_MID,
    DEMAND_MULT_HIGH, ADV_DAYS_EARLY, ADV_DAYS_MID, ADV_DAYS_LATE,
    ADV_FACTOR_EARLY, ADV_FACTOR_MID, ADV_FACTOR_LATE, ADV_FACTOR_LAST,
    PENALTY_FREE_DAYS, PENALTY_MID_DAYS, PENALTY_PCT_FREE, PENALTY_PCT_MID,
    PENALTY_PCT_LAST, CREDIT_LENIENCY_PCT, FREE_BAG_KG,
    OVERWEIGHT_RATE_CENTS_PER_KG,
)


def round_half_up_cents(amount):
    """Round a Decimal to whole cents, half-up, returning an int."""
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def demand_multiplier(service_date):
    """Demand tier from load factor measured BEFORE this booking's seats move
    to sold; load factor counts CONFIRMED legs only (PRD 3.4)."""
    seats_total = service_date["seats_total"]
    seats_sold = service_date["seats_sold"]
    lf = seats_sold / seats_total
    if lf < DEMAND_TIER_MID:
        return Decimal(DEMAND_MULT_LOW)
    elif lf < DEMAND_TIER_HIGH:
        return Decimal(DEMAND_MULT_MID)
    return Decimal(DEMAND_MULT_HIGH)


def advance_factor(service_date):
    """Advance window from whole-day calendar difference between departure_date
    and the current clock date; never negative (PRD 3.4)."""
    dep = parse_date(service_date["departure_date"])
    d = floor_days_between(dep, clock.now())
    if d < 0:
        d = 0
    if d >= ADV_DAYS_EARLY:
        return Decimal(ADV_FACTOR_EARLY)
    elif d >= ADV_DAYS_MID:
        return Decimal(ADV_FACTOR_MID)
    elif d >= ADV_DAYS_LATE:
        return Decimal(ADV_FACTOR_LATE)
    return Decimal(ADV_FACTOR_LAST)


def leg_fare_cents(service_date, fare_class):
    """Per-leg dynamic price for a CASH leg (PRD 3.4):
    round_half_up(base * demand * advance) + surcharge. Per-line rounding,
    before surcharge."""
    base = Decimal(service_date["base_fare_cents"])
    raw = base * demand_multiplier(service_date) * advance_factor(service_date)
    return round_half_up_cents(raw) + fare_class["surcharge_cents"]


def base_penalty_pct(min_leg_departure_date):
    """Days-before-departure tier (PRD 3.6): >=7 -> 0.00; >=1 -> 0.25; else 0.50."""
    dep = parse_date(min_leg_departure_date)
    dbd = floor_days_between(dep, clock.now())
    if dbd >= PENALTY_FREE_DAYS:
        return Decimal(PENALTY_PCT_FREE)
    elif dbd >= PENALTY_MID_DAYS:
        return Decimal(PENALTY_PCT_MID)
    return Decimal(PENALTY_PCT_LAST)


def cancel_settlement(gross_cents, min_leg_departure_date, variant):
    """Return (penalty_cents, net_cents) for a cancel settlement (PRD 3.6).

    variant: 'CASH' uses base penalty; 'TRAVEL_CREDIT' is 10pp more lenient
    (floored at 0).
    """
    base = base_penalty_pct(min_leg_departure_date)
    if variant == "TRAVEL_CREDIT":
        pct = base - Decimal(CREDIT_LENIENCY_PCT)
        if pct < Decimal("0"):
            pct = Decimal("0")
    else:
        pct = base
    penalty = round_half_up_cents(Decimal(gross_cents) * pct)
    net = gross_cents - penalty
    return penalty, net


def cancel_settlement_full_cash(gross_cents):
    """System-cascade refund: always CASH at penalty 0 (PRD 3.2)."""
    return 0, gross_cents


def baggage_fee_cents(weight_kg):
    """Overweight fee (PRD 3.11): 0 if weight <= 23.0kg, else
    round_half_up((weight - 23.0) * 500)."""
    w = Decimal(str(weight_kg))
    free = Decimal(FREE_BAG_KG)
    if w <= free:
        return 0
    return round_half_up_cents((w - free) * Decimal(OVERWEIGHT_RATE_CENTS_PER_KG))
