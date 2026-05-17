"""Calculation rules — caps, RMD, withholding, penalties.

All money is integer cents; rounding is HALF_UP per PRD §2.8.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .constants import (
    CATCHUP_AGE,
    CATCHUP_CAP_CENTS,
    EARLY_ADDER,
    EARLY_PENALTY_AGE,
    EXCESS_PENALTY_RATE,
    MANDATORY_NORMAL_RATE,
    MANDATORY_RMD_RATE,
    REGULAR_CAP_CENTS,
    RMD_AGE,
    SINGLE_LIFE_TABLE,
    UNIFORM_LIFETIME_TABLE,
)


def round_half_up_to_cents(value: Decimal | float | int) -> int:
    """Round a value (already in cents, possibly fractional) HALF_UP to int cents."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def participant_age_on_dec31(date_of_birth: date, year: int) -> int:
    """Age on December 31 of the given year (simply year - birth.year)."""
    return year - date_of_birth.year


def applicable_contribution_cap_cents(date_of_birth: date, clock_year: int) -> int:
    """compute_applicable_contribution_cap per scaffold §1.3."""
    age = participant_age_on_dec31(date_of_birth, clock_year)
    catchup = CATCHUP_CAP_CENTS if age >= CATCHUP_AGE else 0
    return REGULAR_CAP_CENTS + catchup


# ---------------------------------------------------------------------------
# RMD divisor lookups
# ---------------------------------------------------------------------------

def _uniform_lifetime_divisor(age: int) -> float | None:
    """Lookup divisor from Uniform Lifetime table (ages 73..78).

    Returns None when age is below 73 (no RMD). Ages above 78 use the table's
    upper bound (22.0) as a safe extension.
    """
    if age < RMD_AGE:
        return None
    if age in UNIFORM_LIFETIME_TABLE:
        return UNIFORM_LIFETIME_TABLE[age]
    # Extension: ages above table use the smallest (and oldest) divisor
    return UNIFORM_LIFETIME_TABLE[max(UNIFORM_LIFETIME_TABLE.keys())]


def _single_life_divisor(beneficiary_age_at_claim_year: int, year_offset: int) -> float | None:
    """Lookup divisor from Single Life table; decrement by 1 per subsequent year.

    `beneficiary_age_at_claim_year` is the beneficiary's age in the year the
    claim was opened. `year_offset` is the number of full tax_years after the
    claim's opening year (0 for the opening year, 1 for the next, ...).
    """
    base = _interp_single_life(beneficiary_age_at_claim_year)
    if base is None:
        return None
    divisor = base - float(year_offset)
    if divisor <= 0:
        return None
    return divisor


def _interp_single_life(age: int) -> float | None:
    """Linearly interpolate Single Life divisor from anchored table."""
    table = SINGLE_LIFE_TABLE
    keys = sorted(table.keys())
    if age <= keys[0]:
        return table[keys[0]]
    if age >= keys[-1]:
        return table[keys[-1]]
    if age in table:
        return table[age]
    # Find bracketing anchors
    lower = max(k for k in keys if k <= age)
    upper = min(k for k in keys if k >= age)
    if lower == upper:
        return table[lower]
    frac = (age - lower) / (upper - lower)
    return table[lower] + frac * (table[upper] - table[lower])


def compute_rmd_amount_cents(
    *,
    account_type: str,
    inherited_from_participant_id: str | None,
    prior_year_end_balance_cents: int,
    date_of_birth: date,
    tax_year: int,
    inheritance_start_year: int | None,
) -> int:
    """compute_rmd_amount per scaffold §1.3.

    - ROTH owned by original owner -> 0
    - Non-inherited account whose owner is younger than 73 in tax_year -> 0
    - Otherwise divide prior_year_end_balance_cents by table divisor and
      round HALF_UP to whole cents.
    """
    is_inherited = inherited_from_participant_id is not None

    if account_type == "ROTH" and not is_inherited:
        return 0

    age_in_tax_year = participant_age_on_dec31(date_of_birth, tax_year)

    if not is_inherited and age_in_tax_year < RMD_AGE:
        return 0

    if is_inherited:
        if inheritance_start_year is None:
            return 0
        year_offset = max(0, tax_year - inheritance_start_year)
        # beneficiary age at claim-year = age in the year the claim was opened
        beneficiary_age_at_claim_year = inheritance_start_year - date_of_birth.year
        divisor = _single_life_divisor(beneficiary_age_at_claim_year, year_offset)
    else:
        divisor = _uniform_lifetime_divisor(age_in_tax_year)

    if divisor is None or divisor <= 0:
        return 0

    raw = Decimal(prior_year_end_balance_cents) / Decimal(str(divisor))
    return round_half_up_to_cents(raw)


# ---------------------------------------------------------------------------
# Federal withholding
# ---------------------------------------------------------------------------

def compute_federal_withholding(
    *,
    gross_amount_cents: int,
    distribution_reason: str,
    date_of_birth: date,
    clock_year: int,
) -> int:
    """Layered rate per scaffold §1.3.compute_federal_withholding."""
    participant_age = clock_year - date_of_birth.year

    if distribution_reason == "CONVERSION":
        rate = 0.00
    elif distribution_reason == "RMD":
        rate = MANDATORY_RMD_RATE
    elif distribution_reason == "EARLY" and participant_age < EARLY_PENALTY_AGE:
        # Combined single multiplication then single round (per scaffold's
        # `early_with_adder` variant — NOT double-rounded).
        rate = MANDATORY_NORMAL_RATE + EARLY_ADDER  # 0.20
    elif distribution_reason == "EARLY":
        # Age >= 59: no early adder, but normal mandatory rate still applies
        rate = MANDATORY_NORMAL_RATE
    elif distribution_reason == "NORMAL":
        rate = MANDATORY_NORMAL_RATE
    elif distribution_reason == "DEATH":
        rate = 0.00
    elif distribution_reason == "EXCESS_REMOVAL":
        rate = 0.00
    else:
        rate = 0.00

    if rate == 0.00:
        return 0

    raw = Decimal(gross_amount_cents) * Decimal(str(rate))
    return round_half_up_to_cents(raw)


# ---------------------------------------------------------------------------
# Excess contribution penalty
# ---------------------------------------------------------------------------

def assess_excess_contribution(
    *,
    ytd_contribution_cents: int,
    applicable_cap_cents: int,
) -> tuple[int, int] | None:
    """Returns (excess_cents, penalty_cents) when excess > 0, else None."""
    excess = max(0, ytd_contribution_cents - applicable_cap_cents)
    if excess == 0:
        return None
    penalty = round_half_up_to_cents(Decimal(excess) * Decimal(str(EXCESS_PENALTY_RATE)))
    return excess, penalty


def percent_of(cents: int, rate: float) -> int:
    """HALF_UP rounding of `cents * rate` -> int cents."""
    return round_half_up_to_cents(Decimal(cents) * Decimal(str(rate)))


# ---------------------------------------------------------------------------
# Helpers shared with routes/services
# ---------------------------------------------------------------------------

def is_catchup_eligible(date_of_birth: date, clock_year: int) -> bool:
    return participant_age_on_dec31(date_of_birth, clock_year) >= CATCHUP_AGE
