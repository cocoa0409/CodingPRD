"""Calculation rules (SCAFFOLD §1.3 / PRD §2.7, §3.4, §3.7).

All money is whole integer cents. Non-integer intermediates use round-half-up.
Rounding points are pinned per formula and must be honored exactly.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso

# ---- Constants pinned in scaffold §1.3 ----
TIER1_MAX_DAYS = 3
TIER2_MAX_DAYS = 7
TIER2_MULTIPLIER = Decimal("0.90")
TIER3_MULTIPLIER = Decimal("0.80")
TIER1_MULTIPLIER = Decimal("1.00")

DAMAGE_PCT = Decimal("0.60")
WAIVER_CAP_CENTS = 30000
MAX_STRIKES = 2

SIZE_ORDINAL = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4, "XXL": 5}


def round_half_up(value):
    """Round a numeric (Decimal/int) to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -------------------------------------------------------------------------
# recommended_size (PRD §3.2): size chart on chest_cm, half-open [lower, upper)
# -------------------------------------------------------------------------
def recommended_size(chest_cm):
    if chest_cm < 86:
        return "XS"
    if chest_cm < 96:
        return "S"
    if chest_cm < 106:
        return "M"
    if chest_cm < 116:
        return "L"
    if chest_cm < 126:
        return "XL"
    return "XXL"


# -------------------------------------------------------------------------
# fit_verdict (PRD §3.5): ordinal distance between recommended & requested
# -------------------------------------------------------------------------
def fit_verdict(recommended_size_code, requested_size_code):
    delta = abs(SIZE_ORDINAL[recommended_size_code] - SIZE_ORDINAL[requested_size_code])
    if delta == 0:
        return "PASS"
    if delta == 1:
        return "NEEDS_ALTERATION"
    return "FAIL"


# -------------------------------------------------------------------------
# rental_days (PRD §3.4): inclusive day span = whole days + 1
# -------------------------------------------------------------------------
def rental_days(pickup_window_start_iso, return_window_end_iso):
    start = parse_iso(pickup_window_start_iso)
    end = parse_iso(return_window_end_iso)
    whole_days = (end - start).days  # floor of day difference for non-negative spans
    return whole_days + 1


# -------------------------------------------------------------------------
# booking_quote (PRD §3.4): tiered per-day multiplier; round per-day FIRST.
# -------------------------------------------------------------------------
def tier_multiplier(days):
    if days <= TIER1_MAX_DAYS:
        return TIER1_MULTIPLIER
    if days <= TIER2_MAX_DAYS:
        return TIER2_MULTIPLIER
    return TIER3_MULTIPLIER


def booking_quote(catalog, days, damage_waiver_opted):
    multiplier = tier_multiplier(days)
    # Round the effective per-day rate FIRST, then multiply by rental_days.
    effective_daily = round_half_up(Decimal(catalog["daily_rate_cents"]) * multiplier)
    rental_cents = effective_daily * days
    if damage_waiver_opted:
        waiver_cents = catalog["waiver_daily_rate_cents"] * days
    else:
        waiver_cents = 0
    return rental_cents + waiver_cents


# -------------------------------------------------------------------------
# settlement_charges (PRD §3.7): late + damage + waiver + deposit waterfall.
# -------------------------------------------------------------------------
def late_days(returned_at_iso, return_window_end_iso, on_time):
    """Whole calendar days returned strictly past window end; ceil of day diff.

    on_time forces 0 (RETURNED branch).
    """
    if on_time:
        return 0
    returned = parse_iso(returned_at_iso)
    end = parse_iso(return_window_end_iso)
    if returned <= end:
        return 0
    diff_seconds = (returned - end).total_seconds()
    return max(0, math.ceil(diff_seconds / 86400.0))


def damage_fee(catalog, disposition):
    if disposition == "CLEAN":
        return 0
    if disposition == "DAMAGED":
        replacement = catalog["replacement_value_cents"]
        pct_rounded = round_half_up(Decimal(replacement) * DAMAGE_PCT)
        return min(replacement, pct_rounded)
    if disposition == "LOST":
        return catalog["replacement_value_cents"]
    return 0


def settlement_charges(catalog, reservation, returned_at_iso, disposition, on_time):
    ld = late_days(returned_at_iso, reservation["return_window_end_iso"], on_time)
    late_fee_cents = ld * catalog["late_fee_daily_rate_cents"]

    damage_fee_cents = damage_fee(catalog, disposition)

    if reservation["damage_waiver_opted"]:
        waiver_credit_cents = min(damage_fee_cents, WAIVER_CAP_CENTS)
    else:
        waiver_credit_cents = 0

    gross_fees = late_fee_cents + damage_fee_cents - waiver_credit_cents

    deposit = catalog["deposit_cents"]
    applied_from_deposit = min(deposit, gross_fees)
    net_charge_cents = max(0, gross_fees - deposit)
    deposit_refund_cents = deposit - applied_from_deposit

    return {
        "late_days": ld,
        "late_fee_cents": late_fee_cents,
        "damage_fee_cents": damage_fee_cents,
        "waiver_credit_cents": waiver_credit_cents,
        "gross_fees": gross_fees,
        "applied_from_deposit": applied_from_deposit,
        "net_charge_cents": net_charge_cents,
        "deposit_refund_cents": deposit_refund_cents,
    }
