"""Calculation rules (SCAFFOLD §1.3 / PRD §3.3, §3.5, §3.9).

All monetary amounts are integer cents. Percentage components are rounded
half-up at the step the rule specifies, using Decimal (never float).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants (SCAFFOLD §1.3) ----
HEAVY_LBS_THRESHOLD = 60
HEAVY_SURCHARGE_MIN = 20
MATTED_DEMAT_MIN = 25

MATTED_PRICE_PCT = Decimal("0.30")
HEAVY_PRICE_PCT = Decimal("0.15")

NO_SHOW_PCT = Decimal("0.50")
REPEAT_STRIKE_THRESHOLD = 2
REPEAT_PENALTY_CENTS = 1500
NO_SHOW_FEE_CAP_CENTS = 8000

LATE_CANCEL_HOURS = 24
LATE_CANCEL_FLAT_CENTS = 2500

STRIKE_SUSPEND_THRESHOLD = 3
STRIKE_WINDOW_DAYS = 90

TRAVEL_BUFFER_MIN = 15


def round_half_up(value):
    """Round a Decimal/number to a whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_cents, pct):
    """Round half-up `pct` (Decimal) of an integer cent amount to whole cents."""
    return round_half_up(Decimal(amount_cents) * pct)


# ---------------------------------------------------------------------------
# duration_estimate
# ---------------------------------------------------------------------------
def duration_estimate(base_service_minutes, duration_multiplier, weight_lbs,
                      coat_condition, addon_duration_minutes_list):
    # ceil applied once, to tier-scaled minutes only
    tier_minutes = math.ceil(Decimal(str(base_service_minutes)) * Decimal(str(duration_multiplier)))
    size_surcharge = HEAVY_SURCHARGE_MIN if weight_lbs > HEAVY_LBS_THRESHOLD else 0
    matting = MATTED_DEMAT_MIN if coat_condition == "MATTED" else 0
    addon_minutes = sum(addon_duration_minutes_list)
    return int(tier_minutes) + size_surcharge + matting + int(addon_minutes)


# ---------------------------------------------------------------------------
# Shared price assembly (used by quote_price and final_price)
# ---------------------------------------------------------------------------
def _gross_and_discount(tier_base_cents, coat_condition, weight_lbs,
                        addon_total_cents, discount_pct):
    coat_loading = pct_of(tier_base_cents, MATTED_PRICE_PCT) if coat_condition == "MATTED" else 0
    size_loading = pct_of(tier_base_cents, HEAVY_PRICE_PCT) if weight_lbs > HEAVY_LBS_THRESHOLD else 0
    gross = tier_base_cents + coat_loading + size_loading + addon_total_cents
    # discount rounded half-up AFTER gross is summed
    if discount_pct is not None:
        discount = round_half_up(Decimal(gross) * Decimal(str(discount_pct)))
    else:
        discount = 0
    return gross - discount


def quote_price(tier_base_cents, coat_condition, weight_lbs,
                addon_snapshot_total, discount_pct):
    """Forward-looking quote: counts every attached add-on (full requested basket)."""
    return _gross_and_discount(tier_base_cents, coat_condition, weight_lbs,
                               addon_snapshot_total, discount_pct)


def final_price(tier_base_cents, coat_condition, weight_lbs,
                delivered_addon_total, discount_pct):
    """Chronological final price: counts only delivered (non-skipped) add-ons."""
    return _gross_and_discount(tier_base_cents, coat_condition, weight_lbs,
                               delivered_addon_total, discount_pct)


# ---------------------------------------------------------------------------
# no_show_fee
# ---------------------------------------------------------------------------
def no_show_fee(quoted_price_cents, strikes_before):
    base = pct_of(quoted_price_cents, NO_SHOW_PCT)
    if strikes_before >= REPEAT_STRIKE_THRESHOLD:
        fee = base + REPEAT_PENALTY_CENTS
    else:
        fee = base
    return min(fee, NO_SHOW_FEE_CAP_CENTS)


# ---------------------------------------------------------------------------
# late_cancel_fee
# ---------------------------------------------------------------------------
def hours_out(slot_start, now):
    """Whole-hour gap from now to slot_start, floored. Negative if slot is past."""
    delta_seconds = (slot_start - now).total_seconds()
    return math.floor(delta_seconds / 3600.0)


def is_late_cancel(slot_start, now):
    """Late when the whole-hour gap is fewer than LATE_CANCEL_HOURS (24h out is NOT late)."""
    return hours_out(slot_start, now) < LATE_CANCEL_HOURS


def late_cancel_fee():
    return LATE_CANCEL_FLAT_CENTS
