"""Calculation rules (SCAFFOLD §1.3, PRD §3.3, §3.7, §3.9, §3.10).

All money is integer cents. Rounding is round-half-up to whole cents.
"""
from decimal import Decimal, ROUND_HALF_UP

import db


def round_half_up(value):
    """Round a numeric value (cents, possibly fractional) to whole cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def unit_markup_cents(wholesale_cost_cents):
    """Marginal banded markup over wholesale unit cost; rounded half-up per unit.

    band A: 0..5000        -> 0.45
    band B: 5001..20000    -> 0.30 (next 15000)
    band C: above 20000    -> 0.18
    """
    wc = wholesale_cost_cents
    a = min(wc, db.BAND_A_CAP_CENTS)
    b = min(max(wc - db.BAND_A_CAP_CENTS, 0), db.BAND_B_CAP_CENTS - db.BAND_A_CAP_CENTS)
    c = max(wc - db.BAND_B_CAP_CENTS, 0)
    raw = (Decimal(a) * Decimal(str(db.BAND_A_RATE))
           + Decimal(b) * Decimal(str(db.BAND_B_RATE))
           + Decimal(c) * Decimal(str(db.BAND_C_RATE)))
    return round_half_up(raw)


def part_line_pricing(wholesale_cost_cents, quantity):
    """Return (unit_price_cents, line_total_cents).

    Per-unit markup is rounded BEFORE multiplying by quantity.
    """
    markup = unit_markup_cents(wholesale_cost_cents)
    unit_price = wholesale_cost_cents + markup
    line_total = unit_price * quantity
    return unit_price, line_total


def quote_estimate_total(estimated_labor_hours, labor_rate_cents_per_hour,
                         estimated_parts_cents, tow_fee_cents,
                         labor_discount_pct=None):
    """Forward-looking provisional estimate (PRD §3.3).

    labor_discount_pct is the fleet discount fraction (None for retail).
    """
    labor_cents = round_half_up(
        Decimal(str(estimated_labor_hours)) * Decimal(labor_rate_cents_per_hour))
    labor_after_fleet = labor_cents
    if labor_discount_pct is not None:
        labor_after_fleet = round_half_up(
            Decimal(labor_cents) * (Decimal("1") - Decimal(str(labor_discount_pct))))
    return labor_after_fleet + estimated_parts_cents + tow_fee_cents


def final_job_total(base_hours, addon_hours, labor_rate_cents_per_hour,
                    parts_cents, tow_cents, labor_discount_pct=None):
    """Final total from actuals (PRD §3.10).

    Hours summed first, single product rounded once. Parts already-rounded sum.
    """
    total_hours = Decimal(str(base_hours)) + Decimal(str(addon_hours))
    labor_cents = round_half_up(total_hours * Decimal(labor_rate_cents_per_hour))
    labor_after_fleet = labor_cents
    if labor_discount_pct is not None:
        labor_after_fleet = round_half_up(
            Decimal(labor_cents) * (Decimal("1") - Decimal(str(labor_discount_pct))))
    return labor_after_fleet + parts_cents + tow_cents


def fleet_headroom_ok(outstanding_balance_cents, projected_charge_cents, credit_limit_cents):
    """Inclusive boundary: projected == limit PASSES, projected == limit + 1 FAILS."""
    projected = outstanding_balance_cents + projected_charge_cents
    return projected <= credit_limit_cents
