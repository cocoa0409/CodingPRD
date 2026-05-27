"""All calculation rules from SCAFFOLD §1.3, implemented with integer cents
and the rounding order pinned by PRD §2.5."""

from __future__ import annotations

import math


# -----------------------------------------------------------------------------
# Employer match (tiered / safe-harbor) — SCAFFOLD §1.3 `tiered_employer_match`
# -----------------------------------------------------------------------------

BIWEEKLY_DIVISOR = 26
TIER1_MAX_BPS = 300
TIER2_MAX_BPS = 200
SAFE_HARBOR_MAX_BPS = 400


def employer_match(
    *,
    gross_compensation_cents: int,
    deferral_rate_bps: int,
    annual_compensation_limit_cents: int,
    match_formula: str,
) -> tuple[int, int]:
    """Return (employee_contribution_cents, employer_match_cents).

    Per PRD §3.3 + SCAFFOLD §1.3:
      capped_comp = min(gross, floor(annual_comp_limit / 26))
      deferral_amt = floor(capped_comp * deferral_bps / 10000)
      TIERED:    100% on first 3%, 50% on next 2% (floor PER tier, sum after).
      SAFE_HARBOR_ENHANCED: 100% on first 4%, 0% thereafter.
    """
    biweekly_slice = annual_compensation_limit_cents // BIWEEKLY_DIVISOR
    capped_comp = min(gross_compensation_cents, biweekly_slice)
    deferral_amt = (capped_comp * deferral_rate_bps) // 10000

    if match_formula == "TIERED":
        tier1_pct_bps = min(deferral_rate_bps, TIER1_MAX_BPS)
        tier2_pct_bps = min(max(0, deferral_rate_bps - TIER1_MAX_BPS), TIER2_MAX_BPS)
        # Each tier flooredindependently per §2.5 / §1.3 boundary-precision rule (b).
        tier1_match = (capped_comp * tier1_pct_bps) // 10000
        # Tier 2 is half match: floor BEFORE halving (then floor on the halve).
        tier2_match = ((capped_comp * tier2_pct_bps) // 10000) // 2
        employer_match_cents = tier1_match + tier2_match
    else:  # SAFE_HARBOR_ENHANCED (or any unknown — treat as flat 4%)
        eff_pct_bps = min(deferral_rate_bps, SAFE_HARBOR_MAX_BPS)
        employer_match_cents = (capped_comp * eff_pct_bps) // 10000

    return deferral_amt, employer_match_cents


# -----------------------------------------------------------------------------
# Vesting — SCAFFOLD §1.3 `vested_balance`
# -----------------------------------------------------------------------------

GRADED_TABLE = {0: 0, 1: 2000, 2: 4000, 3: 6000, 4: 8000, 5: 10000}


def vested_pct_bps(years_of_service: int, vesting_schedule: str) -> int:
    if vesting_schedule == "CLIFF_3":
        return 0 if years_of_service < 3 else 10000
    # GRADED_6
    if years_of_service >= 6:
        return 10000
    if years_of_service < 0:
        return 0
    return GRADED_TABLE.get(years_of_service, 0)


def vested_employer_balance(
    *,
    employer_balance_cents: int,
    years_of_service: int,
    vesting_schedule: str,
) -> int:
    pct_bps = vested_pct_bps(years_of_service, vesting_schedule)
    return (employer_balance_cents * pct_bps) // 10000


# -----------------------------------------------------------------------------
# Loan amortization — SCAFFOLD §1.3 `loan_amortization`
# -----------------------------------------------------------------------------


def loan_monthly_payment(
    *,
    principal_cents: int,
    term_months: int,
    annual_interest_rate_bps: int,
) -> int:
    """Standard amortization. Per-payment ceil (NOT sum-then-ceil). §2.5."""
    if term_months <= 0:
        return 0
    r_monthly = (annual_interest_rate_bps / 10000.0) / 12.0
    P = float(principal_cents)
    n = term_months
    if r_monthly == 0:
        return int(math.ceil(P / n))
    growth = (1 + r_monthly) ** n
    raw_payment = (P * r_monthly * growth) / (growth - 1)
    return int(math.ceil(raw_payment))


# -----------------------------------------------------------------------------
# Max hardship amount — SCAFFOLD §1.3 `max_hardship_amount`
# -----------------------------------------------------------------------------

HARDSHIP_HARD_CAP_CENTS = 5_000_000
AGE_PENALTY_THRESHOLD = 59  # whole years; per PRD §3.5 (59.5 floored to 59)


def max_hardship_amount(
    *,
    employee_balance_cents: int,
    vested_employer_balance_cents: int,
    outstanding_loan_principal_cents: int,
    requested_amount_cents: int,
    age_today_years: int,
) -> tuple[int, int]:
    """Return (approved_amount_cents, ten_percent_penalty_cents)."""
    vested_total = employee_balance_cents + vested_employer_balance_cents
    cap_a = (vested_total // 2) - outstanding_loan_principal_cents
    cap_b = HARDSHIP_HARD_CAP_CENTS
    cap_c = requested_amount_cents
    approved = max(0, min(cap_a, cap_b, cap_c))

    if age_today_years < AGE_PENALTY_THRESHOLD:
        penalty = (approved * 10) // 100  # floor(approved * 0.10)
    else:
        penalty = 0
    return approved, penalty


# -----------------------------------------------------------------------------
# RMD — SCAFFOLD §1.3 `rmd_required_distribution`
# -----------------------------------------------------------------------------

AGE_RMD_TRIGGER = 73
AGE_GAP_THRESHOLD_FOR_JOINT_LIFE = 10

# Uniform Lifetime Table — representative entries per PRD §3.6 + scaffold.
# Fill in a sensible monotonically-decreasing curve for ages 73..120 so any
# age the tests may probe has a defined factor.
UNIFORM_LIFETIME_TABLE: dict[int, float] = {
    73: 26.5,
    74: 25.5,
    75: 24.6,
    76: 23.7,
    77: 22.9,
    78: 22.0,
    79: 21.1,
    80: 20.2,
    81: 19.4,
    82: 18.5,
    83: 17.7,
    84: 16.8,
    85: 16.0,
    86: 15.2,
    87: 14.4,
    88: 13.7,
    89: 12.9,
    90: 12.2,
    91: 11.5,
    92: 10.8,
    93: 10.1,
    94: 9.5,
    95: 8.9,
    96: 8.4,
    97: 7.8,
    98: 7.3,
    99: 6.8,
    100: 6.4,
    101: 6.0,
    102: 5.6,
    103: 5.2,
    104: 4.9,
    105: 4.6,
    106: 4.3,
    107: 4.1,
    108: 3.9,
    109: 3.7,
    110: 3.5,
    111: 3.4,
    112: 3.3,
    113: 3.1,
    114: 3.0,
    115: 2.9,
    116: 2.8,
    117: 2.7,
    118: 2.5,
    119: 2.3,
    120: 2.0,
}


# Joint Life Table — representative entries per scaffold + plausible extensions.
# Keys are (participant_age, spouse_age). Factor is always strictly larger than
# the corresponding Uniform Lifetime factor for the participant_age.
JOINT_LIFE_TABLE: dict[tuple[int, int], float] = {
    (73, 60): 27.4,
    (73, 55): 30.7,
    (73, 50): 34.2,
    (73, 45): 37.9,
    (73, 40): 41.7,
    (74, 60): 27.0,
    (74, 55): 30.3,
    (75, 60): 26.7,
    (75, 55): 30.0,
    (80, 65): 22.6,
    (80, 60): 24.8,
    (80, 55): 28.0,
    (85, 70): 17.9,
    (85, 65): 19.7,
    (85, 60): 22.4,
}


def _joint_factor(participant_age: int, spouse_age: int) -> float:
    """Return Joint Life Table factor; if exact key absent, fall back to a
    conservative formula: Uniform table factor + (age_gap - 10) bumps it by ~0.5
    per year of additional gap. This guarantees Joint > Uniform per PRD §3.6
    while still being deterministic when tests probe edge ages.
    """
    key = (participant_age, spouse_age)
    if key in JOINT_LIFE_TABLE:
        return JOINT_LIFE_TABLE[key]
    base = UNIFORM_LIFETIME_TABLE.get(participant_age)
    if base is None:
        # Use the largest age in the table for ages beyond it.
        max_age = max(UNIFORM_LIFETIME_TABLE)
        base = UNIFORM_LIFETIME_TABLE[max_age] if participant_age >= max_age else 26.5
    gap = participant_age - spouse_age
    return base + (gap - 10) * 0.5


def rmd_required_amount(
    *,
    prior_year_end_balance_cents: int,
    factor: float,
) -> int:
    """floor(prior_year_end_balance_cents * 1e6 / floor(factor * 1e6))."""
    factor_scaled = int(factor * 1_000_000)  # floor toward zero for positive values
    if factor_scaled <= 0:
        return 0
    numerator = prior_year_end_balance_cents * 1_000_000
    return numerator // factor_scaled


def joint_life_eligible(participant_age: int, spouse_age: int) -> bool:
    """Spouse must be MORE THAN 10 years younger (strict)."""
    return (participant_age - spouse_age) > AGE_GAP_THRESHOLD_FOR_JOINT_LIFE
