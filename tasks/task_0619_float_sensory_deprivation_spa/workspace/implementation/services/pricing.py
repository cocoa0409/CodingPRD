"""Pricing / deposit / refund calculations (SCAFFOLD §1.3, PRD §3.5-3.7).

All money is integer cents. Non-integer results round half-up (PRD §2.5).
Decimal is used throughout — never float.
"""
import math
from decimal import Decimal

from constants import (
    NINETY_MIN_MULTIPLIER,
    COUPLES_SURCHARGE_CENTS,
    DEPOSIT_FLAT_CENTS,
    CYCLE_LENGTH_DAYS,
)
from helpers import round_half_up


def deposit_for(is_couples):
    """Flat deposit, doubled for couples (PRD §3.5)."""
    d = DEPOSIT_FLAT_CENTS
    if is_couples:
        d = d * 2
    return d


def provisional_charge(plan, session_minutes, is_couples, membership):
    """Provisional charge computed once at booking creation from BOOKED minutes.

    Order (PRD §3.5): base = retail; 90-min multiply+round; couples double;
    then member discount (ACTIVE membership) multiply+round. Discount applied
    AFTER couples doubling.
    """
    base = Decimal(plan["retail_float_cents"])
    if session_minutes == 90:
        base = Decimal(round_half_up(base * NINETY_MIN_MULTIPLIER))
    if is_couples:
        base = base * 2
    if membership is not None and membership["status"] == "ACTIVE":
        disc = Decimal(str(plan["member_discount_pct"]))
        base = Decimal(round_half_up(base * (Decimal(1) - disc)))
    return int(base)


def final_charge(plan, realized_minutes, is_couples, membership):
    """Final charge at completion from REALIZED minutes (defaults to booked).

    Order (PRD §3.6): base = retail; 90-min multiply+round; couples double then
    + COUPLES_SURCHARGE_CENTS; then member discount multiply+round. The couples
    surcharge appears only here, never in the provisional estimate.
    """
    base = Decimal(plan["retail_float_cents"])
    if realized_minutes == 90:
        base = Decimal(round_half_up(base * NINETY_MIN_MULTIPLIER))
    if is_couples:
        base = base * 2 + COUPLES_SURCHARGE_CENTS
    if membership is not None and membership["status"] == "ACTIVE":
        disc = Decimal(str(plan["member_discount_pct"]))
        base = Decimal(round_half_up(base * (Decimal(1) - disc)))
    return int(base)


def refund_valuation(membership, now):
    """Authoritative forward-looking proration of the captured monthly fee.

    days_remaining = ceil((cycle_end_utc - now) / 1 day), floored at 0.
    refund = round_half_up(monthly_fee_snapshot * days_remaining / CYCLE_LENGTH_DAYS).
    (PRD §3.7)
    """
    fee = membership.get("monthly_fee_cents_snapshot")
    cycle_end = membership.get("cycle_end_utc")
    if fee is None or cycle_end is None:
        return 0
    delta_seconds = (cycle_end - now).total_seconds()
    if delta_seconds <= 0:
        days_remaining = 0
    else:
        days_remaining = math.ceil(delta_seconds / 86400.0)
    if days_remaining < 0:
        days_remaining = 0
    refund = round_half_up(Decimal(fee) * Decimal(days_remaining) / Decimal(CYCLE_LENGTH_DAYS))
    return refund


def credits_required(is_couples):
    """2 for couples, else 1 (SCAFFOLD §1.3 credits_required)."""
    return 2 if is_couples else 1
