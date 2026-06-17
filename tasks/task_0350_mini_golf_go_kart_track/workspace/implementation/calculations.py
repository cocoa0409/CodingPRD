"""Pricing, combo-credit, loyalty, and capacity calculations per PRD §3.

All money is integer cents. Fractional results are rounded ONCE at the end of
each calculation with round-half-up.
"""
from decimal import Decimal
from util import round_half_up

GROUP_MIN_SIZE = 4
LOYALTY_THRESHOLD_CENTS = 5000
LOYALTY_BONUS_PCT = Decimal("0.10")


def effective_units(plan, units):
    """Effective unit count: capped for WRISTBAND with a positive cap."""
    eu = units
    if plan["mode"] == "WRISTBAND" and plan["wristband_unit_cap"] > 0:
        eu = min(units, plan["wristband_unit_cap"])
    return eu


def booking_price(plan, slot_window, units, party_size):
    """Compute gross_price_cents per PRD §3.7. Step order is pinned:
    per-unit price -> raw -> group discount -> single round at the end.
    """
    eu = effective_units(plan, units)

    per_unit = plan["base_price_cents"]
    if slot_window == "PEAK":
        per_unit = per_unit + plan["peak_surcharge_cents"]

    if plan["mode"] == "WRISTBAND":
        raw = per_unit * party_size
    else:
        raw = per_unit * eu * party_size

    discount_factor = Decimal("1")
    if party_size >= GROUP_MIN_SIZE:
        discount_factor = Decimal("1") - Decimal(str(plan["group_discount_pct"]))

    gross = round_half_up(Decimal(raw) * discount_factor)
    return gross


def combo_credit_application(plan, combo_pass, gross_price_cents, units, party_size):
    """Return (credits_applied, cash_due_cents) per PRD §3.7.

    Credits cover whole activity units first; cash covers the remainder.
    """
    if combo_pass is None or combo_pass["status"] != "ACTIVE":
        return 0, gross_price_cents

    eu = effective_units(plan, units)
    billable_units = eu * party_size
    if billable_units <= 0:
        return 0, gross_price_cents

    credits_remaining = max(0, combo_pass["total_credits"] - combo_pass["credits_redeemed"])
    credits_applied = min(credits_remaining, billable_units)
    if credits_applied <= 0:
        return 0, gross_price_cents

    covered_fraction = Decimal(credits_applied) / Decimal(billable_units)
    credit_value = round_half_up(Decimal(gross_price_cents) * covered_fraction)
    cash_due = max(0, gross_price_cents - credit_value)
    return credits_applied, cash_due


def loyalty_bonus(total_loaded_before, amount_cents):
    """Bonus earned ONLY on the single top-up that crosses the threshold."""
    if total_loaded_before < LOYALTY_THRESHOLD_CENTS and \
            (total_loaded_before + amount_cents) >= LOYALTY_THRESHOLD_CENTS:
        return round_half_up(Decimal(amount_cents) * LOYALTY_BONUS_PCT)
    return 0
