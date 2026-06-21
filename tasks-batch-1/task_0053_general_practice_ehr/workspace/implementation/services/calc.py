"""Calculation rules (SCAFFOLD §1.3, PRD §2.7 / §3.3 / §3.5 / §3.10).

All money is in whole cents; every fractional cent rounds HALF UP (away from
zero). Use Decimal exclusively — never float — for money.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# E/M tiered multipliers by level (PRD §3.3).
EM_LEVEL_MULTIPLIER = {
    1: Decimal("0.5"),
    2: Decimal("0.8"),
    3: Decimal("1.0"),
    4: Decimal("1.4"),
    5: Decimal("2.0"),
}

# Network contractual write-down applied once at finalize (PRD §3.5).
CONTRACTUAL_ADJ_RATE = Decimal("0.10")

# HEDIS inclusive age windows (PRD §3.10).
MEASURE_AGE_WINDOW = {
    "CIS_FLU": (0, 18),
    "BCS_MAMMOGRAM": (50, 74),
    "CBP_BP_CONTROL": (18, 85),
    "MED_ADHERENCE": (18, 120),
}

# Fixed reporting year for open-care-gap counting (SCAFFOLD §1.3 open_care_gaps).
CURRENT_MEASUREMENT_YEAR = 2026

# Adherence threshold: a single dispensed fill satisfies MED_ADHERENCE (PRD §3.7).
MED_ADHERENCE_MIN_FILLS = 1


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def charge_line_amount(base_fee_cents: int, requires_em_level: bool,
                       em_level, units: int) -> int:
    """Per-line amount, rounded half up to whole cents (SCAFFOLD §1.3 charge_line_amount)."""
    base = Decimal(base_fee_cents)
    if requires_em_level:
        mult = EM_LEVEL_MULTIPLIER[int(em_level)]
    else:
        mult = Decimal("1.0")
    raw = base * mult * Decimal(units)
    return _round_half_up(raw)


def visit_billed_total_provisional(line_amounts) -> int:
    """Provisional total: plain sum of already-rounded line amounts (no adjustment)."""
    return sum(int(a) for a in line_amounts)


def visit_billed_total_final(line_amounts) -> int:
    """Final total: provisional sum * (1 - CONTRACTUAL_ADJ_RATE), rounded once."""
    provisional = Decimal(visit_billed_total_provisional(line_amounts))
    final = provisional * (Decimal("1") - CONTRACTUAL_ADJ_RATE)
    return _round_half_up(final)


def hedis_age_at_year_end(date_of_birth: str, measurement_year: int) -> int:
    """Whole years between DOB and Dec 31 of measurement_year via days/365.25 floor."""
    dob = date.fromisoformat(date_of_birth)
    dec31 = date(measurement_year, 12, 31)
    elapsed_days = (dec31 - dob).days
    return int(Decimal(elapsed_days) / Decimal("365.25"))  # truncates toward zero == floor for positives


def hedis_eligibility(date_of_birth: str, sex: str, measure_type: str,
                      measurement_year: int) -> bool:
    """Eligibility = sex_ok AND (min_age <= age <= max_age), inclusive (PRD §3.10)."""
    age = hedis_age_at_year_end(date_of_birth, measurement_year)
    min_age, max_age = MEASURE_AGE_WINDOW[measure_type]
    sex_ok = (measure_type != "BCS_MAMMOGRAM") or (sex == "F")
    return bool(sex_ok and (min_age <= age <= max_age))


def hedis_rate_pct(numerator: int, denominator: int):
    """Percentage to 2 decimals, round half up; integer 0 when denominator==0."""
    if denominator == 0:
        return 0
    scaled = (Decimal(numerator) * Decimal(10000)) / Decimal(denominator)
    whole = scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(whole / Decimal(100))
