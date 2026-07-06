"""Calculation rules (scaffold §1.3 / PRD §3.4, §3.8, §2.9)."""
import math
from decimal import Decimal, ROUND_HALF_UP

BASE_FEE_CENTS = 150000
BLOCK_FEE_CENTS = 20000
SPECIMEN_FEE_CENTS = 5000
HOMICIDE_MULT = Decimal("1.5")
SECONDS_PER_DAY = 86400
POSITIVE_THRESHOLD_MG_DL = 80


def _round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def autopsy_fee_estimate(duration_minutes, case_type):
    """Forward-looking quote at scheduling."""
    blocks = math.ceil(duration_minutes / 30)
    duration_surcharge = blocks * BLOCK_FEE_CENTS
    subtotal = BASE_FEE_CENTS + duration_surcharge
    if case_type == "HOMICIDE":
        subtotal = _round_half_up_int(Decimal(subtotal) * HOMICIDE_MULT)
    return subtotal


def autopsy_fee_final(scheduled_for, clock_now, duration_minutes, billable_specimen_count, case_type):
    """Actual bill at completion. Multiplier applied strictly AFTER specimen add-on."""
    elapsed_seconds = (clock_now - scheduled_for).total_seconds()
    elapsed_min = math.floor(elapsed_seconds / 60)
    billed_min = max(elapsed_min, duration_minutes)
    blocks = math.ceil(billed_min / 30)
    duration_surcharge = blocks * BLOCK_FEE_CENTS
    specimen_addon = billable_specimen_count * SPECIMEN_FEE_CENTS
    subtotal = BASE_FEE_CENTS + duration_surcharge + specimen_addon
    if case_type == "HOMICIDE":
        subtotal = _round_half_up_int(Decimal(subtotal) * HOMICIDE_MULT)
    return subtotal


def indigent_county_payable(itemized_cost_cents, statutory_allowance_cents, held_estate_value_cents):
    """Waterfall: estate offset first, then statutory cap (pinned order)."""
    cost_after_estate = max(itemized_cost_cents - held_estate_value_cents, 0)
    return min(cost_after_estate, statutory_allowance_cents)


def occupancy_body_days(intake_at, clock_now):
    """Per-body started-day count; 0 elapsed -> 0 days."""
    elapsed_seconds = (clock_now - intake_at).total_seconds()
    if elapsed_seconds <= 0:
        return 0
    return math.ceil(elapsed_seconds / SECONDS_PER_DAY)


def tox_interpretation(ethanol_mg_dl):
    return "POSITIVE" if ethanol_mg_dl >= POSITIVE_THRESHOLD_MG_DL else "NEGATIVE"
