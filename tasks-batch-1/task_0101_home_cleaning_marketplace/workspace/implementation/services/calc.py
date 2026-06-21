"""Calculation rules per scaffold §1.3 / PRD §3.5-3.7.

All money is integer cents. Percentages are applied with Decimal and
rounded half-up per component (never sum-then-round).
"""
from constants import (
    VISIT_MINUTES, MOVE_OUT_MINIMUM_CENTS, FREE_CANCEL_HOURS,
    LATE_CANCEL_HOURS, RESCHEDULE_FEE_CENTS, LATE_CANCEL_PCT,
    NOSHOW_CANCEL_PCT, PAYOUT_PCT, loyalty_tier_pct,
)
from util import pct_of_cents, add_minutes


def visit_window(home_size, scheduled_start):
    """Return scheduled_end = start + VISIT_MINUTES[home_size] (whole minutes)."""
    duration = VISIT_MINUTES[home_size]
    return add_minutes(scheduled_start, duration)


def price_quote(is_reclean, plan, home_size, add_ons, supplies_provided_by,
                lifetime_booking_count):
    """price_quote (§1.3 / PRD §3.6). Returns integer cents.

    Reclean visits quote 0. Otherwise:
      base = plan.base_price_cents[home_size]
      surcharge += round_half_up(base * deep_clean_pct) if DEEP_CLEAN
      surcharge += round_half_up(base * move_out_pct)   if MOVE_OUT
      supplies = plan.supplies_fee_cents if CLEANER else 0
      subtotal = base + surcharge + supplies
      discount = round_half_up(subtotal * loyalty_tier_pct(count))
      priced = subtotal - discount
      if MOVE_OUT: priced = max(priced, MOVE_OUT_MINIMUM_CENTS)
    Per-component rounding (each surcharge and the discount rounded before sum).
    """
    if is_reclean:
        return 0
    base = int(plan["base_price_cents"][home_size])
    surcharge = 0
    if "DEEP_CLEAN" in add_ons:
        surcharge += pct_of_cents(base, plan["deep_clean_surcharge_pct"])
    if "MOVE_OUT" in add_ons:
        surcharge += pct_of_cents(base, plan["move_out_surcharge_pct"])
    supplies = int(plan["supplies_fee_cents"]) if supplies_provided_by == "CLEANER" else 0
    subtotal = base + surcharge + supplies
    tier_pct = loyalty_tier_pct(lifetime_booking_count)
    discount = pct_of_cents(subtotal, tier_pct)
    priced = subtotal - discount
    if "MOVE_OUT" in add_ons:
        priced = max(priced, MOVE_OUT_MINIMUM_CENTS)
    return priced


def reschedule_or_cancel_fee(action, quoted_price_cents, scheduled_start,
                             current_clock):
    """reschedule_or_cancel_fee (§1.3 / PRD §3.5). Returns integer cents.

    hours_to_start = (scheduled_start - current_clock) / 3600
    Boundary inclusive on free side: >= FREE_CANCEL_HOURS -> 0.
    Late band  (FREE > hrs >= LATE): RESCHEDULE flat 1500; CANCEL 25% of quote.
    No-show band (hrs < LATE, incl. past start): RESCHEDULE flat 1500;
                                                 CANCEL 50% of quote.
    action is "RESCHEDULE" or "CANCEL".
    """
    delta_seconds = (scheduled_start - current_clock).total_seconds()
    hours_to_start = delta_seconds / 3600.0
    if hours_to_start >= FREE_CANCEL_HOURS:
        return 0
    if hours_to_start >= LATE_CANCEL_HOURS:
        if action == "RESCHEDULE":
            return RESCHEDULE_FEE_CENTS
        return pct_of_cents(quoted_price_cents, LATE_CANCEL_PCT)
    # No-show band.
    if action == "RESCHEDULE":
        return RESCHEDULE_FEE_CENTS
    return pct_of_cents(quoted_price_cents, NOSHOW_CANCEL_PCT)


def cleaner_payout_base(quoted_price_cents):
    """base_payout_cents = round_half_up(quoted_price_cents * PAYOUT_PCT)."""
    return pct_of_cents(quoted_price_cents, PAYOUT_PCT)
