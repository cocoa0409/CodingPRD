"""Calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3.2-3.8). All money in integer cents."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def waiting_period_valid_from(issued_at):
    """valid_from = issued_at + WAITING_PERIOD_HOURS hours (hour precision)."""
    return issued_at + timedelta(hours=C.WAITING_PERIOD_HOURS)


def validity_expires_at(issued_at):
    """expires_at = issued_at + VALIDITY_WINDOW_DAYS days (day precision)."""
    return issued_at + timedelta(days=C.VALIDITY_WINDOW_DAYS)


def filing_deadline(ceremony_date):
    """filing_deadline = ceremony_date + RETURN_FILING_DAYS days."""
    return ceremony_date + timedelta(days=C.RETURN_FILING_DAYS)


def whole_years(date_of_birth, now):
    """Number of full completed years between date_of_birth and now."""
    years = now.year - date_of_birth.year
    # Subtract one if this year's birthday has not yet occurred.
    if (now.month, now.day, now.hour, now.minute, now.second, now.microsecond) < (
        date_of_birth.month, date_of_birth.day, date_of_birth.hour,
        date_of_birth.minute, date_of_birth.second, date_of_birth.microsecond,
    ):
        years -= 1
    return years


def poverty_threshold_for(household_size):
    return C.BASE_POVERTY_CENTS + (household_size - 1) * C.PER_PERSON_POVERTY_CENTS


def waiver_cap(declared_monthly_income_cents, household_size):
    """waiver_cap_calc: scale by shortfall ratio vs poverty threshold."""
    threshold = poverty_threshold_for(household_size)
    shortfall_ratio = (threshold - declared_monthly_income_cents) / threshold
    if shortfall_ratio >= C.DEEP_NEED_RATIO:
        return C.FULL_WAIVER_CAP_CENTS
    return C.PARTIAL_WAIVER_CAP_CENTS


def _round_half_up(value):
    """Round a Decimal to whole cents, half rounds up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def amendment_fee(amendment_type, resubmit_count):
    """amendment_fee_calc: round each percentage component FIRST, then sum."""
    base = C.CLERICAL_BASE_CENTS if amendment_type == "CLERICAL" else C.SUBSTANTIVE_BASE_CENTS
    expedite_component = _round_half_up(Decimal(base) * Decimal(C.EXPEDITE_PCT))
    penalty_component = _round_half_up(
        Decimal(base) * Decimal(C.RESUBMIT_PENALTY_PCT) * Decimal(resubmit_count)
    )
    return base + expedite_component + penalty_component


def certified_copy_gross(copies_requested, is_confidential, requester_kind):
    """Gross fee after tier -> surcharge -> government exemption (before waiver)."""
    # Step 1: tiered per-copy total.
    first = min(copies_requested, C.FIRST_TIER_COPIES) * C.FIRST_TIER_CENTS
    extra = max(0, copies_requested - C.FIRST_TIER_COPIES) * C.ADDITIONAL_COPY_CENTS
    gross = first + extra
    # Step 2: confidential surcharge (flat, once).
    if is_confidential:
        gross += C.CONFIDENTIAL_SURCHARGE_CENTS
    # Step 3: government exemption (after surcharge, before waiver).
    if requester_kind == "GOVERNMENT":
        gross = 0
    return gross


def waiver_absorption(gross, waiver):
    """absorbed = min(gross, remaining cap). Returns (absorbed, net_fee)."""
    remaining = waiver["max_waivable_cents"] - waiver["consumed_cents"]
    absorbed = min(gross, max(0, remaining))
    return absorbed, gross - absorbed
