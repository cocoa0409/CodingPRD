"""Monetary calculations (SCAFFOLD §1.3 / PRD §2.6, §3).

All money is integer cents. Every fractional intermediate is rounded to whole
cents with round-half-up. Multi-component totals follow the pinning rule:
round each component to whole cents, then sum.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- quote_amount constants ----
PANE_RATE_T1_CENTS = 300
PANE_RATE_T2_CENTS = 250
PANE_RATE_T3_CENTS = 200
SQFT_RATE_CENTS = 90
MIN_JOB_CENTS = 9900
HIGH_RISE_STORY_THRESHOLD = 3
HIGH_RISE_SURCHARGE_PCT = Decimal("0.20")
GUTTER_FLAT_CENTS = 7500
SCREEN_PER_PANE_CENTS = 150
SOFT_WASH_RATE_CENTS = 25
SOFT_WASH_MIN_CENTS = 12000

# ---- deposit_requirement constants ----
DEPOSIT_THRESHOLD_CENTS = 30000
DEPOSIT_PCT = Decimal("0.25")

# ---- visit_charge constants ----
RESCHEDULE_DISCOUNT_THRESHOLD = 2
RESCHEDULE_DISCOUNT_PCT = Decimal("0.10")

# ---- reclean_credit constants ----
AFTER_PHOTO_DOC_THRESHOLD = 2
PARTIAL_CREDIT_PCT = Decimal("0.50")


def round_half_up(value):
    """Round a numeric/Decimal value to the nearest whole integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def addon_charge_cents(addon_code, prop):
    """Per-add-on charge over a property, mirroring quote_amount add-on rules.

    Used both for the quote's addon_total and for VisitAddOn.charge_cents.
    """
    if addon_code == "GUTTER":
        return GUTTER_FLAT_CENTS
    if addon_code == "SCREEN":
        return SCREEN_PER_PANE_CENTS * int(prop["pane_count"])
    if addon_code == "SOFT_WASH":
        sw = round_half_up(Decimal(str(prop["soft_wash_sqft"])) * SOFT_WASH_RATE_CENTS)
        return max(sw, SOFT_WASH_MIN_CENTS)
    raise ValueError("unknown addon code")


def quote_amount(pricing_basis, prop, addon_codes):
    """Return (base_price_cents, addon_total_cents, quoted_total_cents)."""
    if pricing_basis == "PANE_COUNT":
        n = int(prop["pane_count"])
        base = 0
        base += min(n, 20) * PANE_RATE_T1_CENTS
        base += min(max(n - 20, 0), 30) * PANE_RATE_T2_CENTS
        base += max(n - 50, 0) * PANE_RATE_T3_CENTS
        base = max(base, MIN_JOB_CENTS)
    else:  # SQ_FT
        whole_sqft = math.ceil(Decimal(str(prop["glass_sqft"])))
        base = whole_sqft * SQFT_RATE_CENTS
        base = max(base, MIN_JOB_CENTS)

    # high-rise surcharge: threshold on stories, % of base, rounded half-up
    if int(prop["stories"]) >= HIGH_RISE_STORY_THRESHOLD:
        base = base + round_half_up(Decimal(base) * HIGH_RISE_SURCHARGE_PCT)
    base_price_cents = base

    # add-ons: each rounded to whole cents independently, then summed
    addon_total_cents = 0
    for code in addon_codes:
        addon_total_cents += addon_charge_cents(code, prop)

    quoted_total_cents = base_price_cents + addon_total_cents
    return base_price_cents, addon_total_cents, quoted_total_cents


def deposit_requirement(quoted_total_cents):
    if quoted_total_cents >= DEPOSIT_THRESHOLD_CENTS:
        return round_half_up(Decimal(quoted_total_cents) * DEPOSIT_PCT)
    return 0


def visit_charge(per_visit_price_cents, addon_delta_cents, reschedule_count):
    gross = per_visit_price_cents + addon_delta_cents
    if reschedule_count >= RESCHEDULE_DISCOUNT_THRESHOLD:
        gross = gross - round_half_up(Decimal(gross) * RESCHEDULE_DISCOUNT_PCT)
    return max(gross, 0)


def reclean_credit(charge_amount_cents, after_photo_count):
    if after_photo_count >= AFTER_PHOTO_DOC_THRESHOLD:
        return round_half_up(Decimal(charge_amount_cents) * PARTIAL_CREDIT_PCT)
    return charge_amount_cents
