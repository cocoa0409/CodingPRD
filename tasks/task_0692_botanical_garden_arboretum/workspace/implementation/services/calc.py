"""Calculation rules (PRD §3, §2.6 / SCAFFOLD §1.3).

All money is integer cents. Fractional cents round half-up. Several calculations
pin the order of rounding relative to multiplication; those orders are honored.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

TERM_DAYS = 365
DAY_SECONDS = 86400
HOUR_SECONDS = 3600
MEMBER_DISCOUNT_FLOOR_CENTS = 50000
BENEFIT_THRESHOLD_CENTS = 25000
BENEFIT_FMV_CENTS = 2000


def round_half_up(value):
    """Round a real number half-up to the nearest whole integer (cent)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_product(factor_real, multiplier_int):
    """Round (real * int) half-up using exact Decimal arithmetic."""
    return int((Decimal(str(factor_real)) * Decimal(multiplier_int)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# --- Membership join / renewal credit (dual variant) -----------------------
def join_fee_charge(annual_fee_cents):
    """Activate / reinstate: full annual fee for a fresh 365-day term."""
    return annual_fee_cents


def renewal_credit_charge(annual_fee_cents, term_end, clock_now):
    """Renewal credit (PRD §3.2). Evaluation order is pinned.

    1. unused_days = floor-at-0 of ceil((term_end - now) in days)
    2. daily_value = annual_fee_cents / 365  (exact real, not yet rounded)
    3. credit = round_half_up(daily_value * unused_days)  (round ONCE, after multiply)
    4. charge = max(0, annual_fee_cents - credit)
    """
    delta_seconds = (term_end - clock_now).total_seconds()
    if delta_seconds <= 0:
        unused_days = 0
    else:
        unused_days = math.ceil(delta_seconds / DAY_SECONDS)
    unused_days = max(0, unused_days)
    # daily_value * unused_days, rounding exactly once after the multiply.
    credit_cents = int(
        (Decimal(annual_fee_cents) * Decimal(unused_days) / Decimal(TERM_DAYS)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    charge_cents = max(0, annual_fee_cents - credit_cents)
    return charge_cents


# --- Reservation admission -------------------------------------------------
def reservation_admission_cents(ga_price_cents, reciprocal, reciprocal_discount_pct,
                                paid_heads):
    """Per-head rate rounded FIRST, then multiplied by paid_heads (PRD §3.3)."""
    if reciprocal:
        per_head = round_half_up(ga_price_cents * (1 - reciprocal_discount_pct))
    else:
        per_head = ga_price_cents
    return per_head * paid_heads


# --- Event ticket pricing --------------------------------------------------
def event_ticket_charge(list_price_cents, quantity, member_discount_applies,
                        event_discount_pct):
    """Discount + round PER-TICKET first, then multiply by quantity (PRD §3.4)."""
    if member_discount_applies:
        per_ticket = round_half_up(list_price_cents * (1 - event_discount_pct))
    else:
        per_ticket = list_price_cents
    return per_ticket * quantity


# --- Program tuition -------------------------------------------------------
def program_tuition_charge(tuition_cents, member_discount_applies, program_discount_pct):
    """Member program discount applied + rounded half-up (PRD §3.5)."""
    if member_discount_applies:
        return round_half_up(tuition_cents * (1 - program_discount_pct))
    return tuition_cents


# --- Rental pricing --------------------------------------------------------
def rental_hours(starts_at, ends_at):
    """Billable hours: span in hours, partial hour rounds UP (PRD §3.6)."""
    seconds = (ends_at - starts_at).total_seconds()
    return math.ceil(seconds / HOUR_SECONDS)


def rental_price_cents(starts_at, ends_at, hourly_rate_cents, eligible,
                       member_rental_discount_pct):
    """Pinned order: hours -> subtotal -> eligibility -> discount -> price."""
    hours = rental_hours(starts_at, ends_at)
    subtotal_cents = hours * hourly_rate_cents
    if eligible:
        discount_cents = round_half_up(subtotal_cents * member_rental_discount_pct)
    else:
        discount_cents = 0
    return subtotal_cents - discount_cents


# --- Donation deductibility ------------------------------------------------
def donation_deductible_cents(amount_cents, designation):
    """Deductible = gift minus fair-market value of any benefit (PRD §3.7)."""
    if designation == "GENERAL" and amount_cents >= BENEFIT_THRESHOLD_CENTS:
        return amount_cents - BENEFIT_FMV_CENTS
    return amount_cents


# --- Conservancy match -----------------------------------------------------
def conservancy_applied_match(amount_cents, campaign_open, match_ratio,
                              match_cap_cents, matched_total_cents):
    """While OPEN, raw match rounded half-up then clamped by remaining cap."""
    if not campaign_open:
        return 0
    raw_match = round_half_up(amount_cents * match_ratio)
    remaining_cap = max(0, match_cap_cents - matched_total_cents)
    return min(raw_match, remaining_cap)


# --- Guest pass grant ------------------------------------------------------
def guest_pass_grant(tier, grant_household, grant_patron):
    if tier == "INDIVIDUAL":
        return 0
    if tier == "HOUSEHOLD":
        return grant_household
    if tier == "PATRON":
        return grant_patron
    return 0
