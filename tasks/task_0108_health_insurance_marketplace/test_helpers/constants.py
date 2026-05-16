"""Domain thresholds and reference tables.

Every constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations

from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# FPL denominator tables (cents) — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "For coverage year 2025 (version v1), those denominators are
# 1,525,500 cents at household size 1, 2,067,500 cents at size 2,
# 2,609,500 cents at size 3, 3,151,500 cents at size 4, 3,693,500 cents
# at size 5, and 4,235,500 cents at size 6, with each additional member
# beyond six adding 542,000 cents to the denominator. For coverage year
# 2026 (version v2), the corresponding denominators are 1,572,500 cents,
# 2,131,000 cents, 2,689,500 cents, 3,248,000 cents, 3,806,500 cents,
# and 4,365,000 cents, with each additional member beyond six adding
# 558,500 cents."
FPL_TABLE_V1: Dict[int, int] = {
    1: 1_525_500,
    2: 2_067_500,
    3: 2_609_500,
    4: 3_151_500,
    5: 3_693_500,
    6: 4_235_500,
}
FPL_V1_PER_ADDITIONAL: int = 542_000

FPL_TABLE_V2: Dict[int, int] = {
    1: 1_572_500,
    2: 2_131_000,
    3: 2_689_500,
    4: 3_248_000,
    5: 3_806_500,
    6: 4_365_000,
}
FPL_V2_PER_ADDITIONAL: int = 558_500


def fpl_denominator(year: int, household_size: int) -> int:
    """PRD §3.2 denominator lookup. For sizes > 6, add per-additional."""
    if year == 2025:
        table, per_add = FPL_TABLE_V1, FPL_V1_PER_ADDITIONAL
    elif year == 2026:
        table, per_add = FPL_TABLE_V2, FPL_V2_PER_ADDITIONAL
    else:
        raise ValueError(f"FPL table not loaded for coverage_year {year}")
    if household_size <= 6:
        return table[household_size]
    return table[6] + (household_size - 6) * per_add


# ---------------------------------------------------------------------------
# Applicable percentage table — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "a percentage at or above 100.0 and strictly below 150.0
# contributes 0.0% of MAGI (the applicable fraction is 0.0000); at or
# above 150.0 and strictly below 200.0, 2.0% (0.0200); at or above 200.0
# and strictly below 250.0, 4.0% (0.0400); at or above 250.0 and strictly
# below 300.0, 6.0% (0.0600); at or above 300.0 and strictly below 400.0,
# 8.5% (0.0850); at or above 400.0 the applicable fraction is 1.0000."
APPLICABLE_PERCENTAGE_TABLE: List[Tuple[float, float, float]] = [
    (100.0, 150.0, 0.0000),
    (150.0, 200.0, 0.0200),
    (200.0, 250.0, 0.0400),
    (250.0, 300.0, 0.0600),
    (300.0, 400.0, 0.0850),
    (400.0, 99999.0, 1.0000),
]


def applicable_fraction(fpl_percentage: float) -> float:
    """Look up the contribution fraction. PRD §3.3 half-open intervals."""
    for lo, hi, frac in APPLICABLE_PERCENTAGE_TABLE:
        if lo <= fpl_percentage < hi:
            return frac
    # Below 100% — handled separately (Medicaid territory).
    return 0.0


# ---------------------------------------------------------------------------
# Age curve multipliers — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "0.765 for ages 0 through 14, 0.833 for ages 15 through 20,
# 1.000 for ages 21 through 24, 1.061 for ages 25 through 29, 1.150 for
# ages 30 through 34, 1.181 for ages 35 through 39, 1.278 for ages 40
# through 44, 1.444 for ages 45 through 49, 1.706 for ages 50 through 54,
# 2.040 for ages 55 through 59, 2.411 for ages 60 through 63, and 3.000
# for ages 64 and above."
AGE_CURVE: List[Tuple[int, int, float]] = [
    (0, 14, 0.765),
    (15, 20, 0.833),
    (21, 24, 1.000),
    (25, 29, 1.061),
    (30, 34, 1.150),
    (35, 39, 1.181),
    (40, 44, 1.278),
    (45, 49, 1.444),
    (50, 54, 1.706),
    (55, 59, 2.040),
    (60, 63, 2.411),
]
# 64 and above sentinel handled separately.
AGE_CURVE_64_PLUS: float = 3.000


def age_multiplier(age: int) -> float:
    """PRD §3.6 age-bracket lookup."""
    if age >= 64:
        return AGE_CURVE_64_PLUS
    for lo, hi, mult in AGE_CURVE:
        if lo <= age <= hi:
            return mult
    raise ValueError(f"age {age} out of range")


# ---------------------------------------------------------------------------
# Tobacco surcharge — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "If the member is a tobacco user (is_tobacco_user is true)
# and their age at coverage_start_date is at least 21, the per-member
# amount is multiplied by the tobacco surcharge factor of 1.50 and
# rounded half-up to a whole cent a second time."
TOBACCO_SURCHARGE: float = 1.50


# ---------------------------------------------------------------------------
# CSR tier thresholds — PRD §3.3 (csr_tier_classification)
# ---------------------------------------------------------------------------
# PRD §3.3: "A household whose fpl_percentage is strictly below 100.0
# lies in Medicaid territory; ... A household at or above 100.0 and
# strictly below 138.0 is assigned CSR_PLUS, ... A household at or above
# 138.0 and strictly below 150.0 is CSR_94; at or above 150.0 and
# strictly below 200.0 it is CSR_87; at or above 200.0 and strictly below
# 250.0 it is CSR_73. A household at or above 250.0 receives no CSR and
# csr_eligibility is NONE."
CSR_BOUNDARIES: List[Tuple[float, float, str]] = [
    (0.0, 100.0, "NONE"),       # Medicaid territory
    (100.0, 138.0, "CSR_PLUS"),
    (138.0, 150.0, "CSR_94"),
    (150.0, 200.0, "CSR_87"),
    (200.0, 250.0, "CSR_73"),
    (250.0, 99999.0, "NONE"),
]


# ---------------------------------------------------------------------------
# Medicaid expansion table — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3 names CA, NY, WA (expansion); TX, FL, GA (non-expansion).
MEDICAID_EXPANSION: Dict[str, bool] = {
    "CA": True,
    "NY": True,
    "WA": True,
    "TX": False,
    "FL": False,
    "GA": False,
}


# ---------------------------------------------------------------------------
# Grace period & termination thresholds — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "the first day of the oldest unpaid month plus 30 days."
GRACE_PERIOD_DAYS: int = 30

# PRD §3.7: "Day 91 of non-payment triggers termination."
TERMINATION_THRESHOLD_DAYS: int = 90

# PRD §3.4: "Verification requires that the event_date lie within 60
# calendar days of the logical-clock present."
SEP_WINDOW_DAYS: int = 60

# PRD §3.4: "window_closes_on is exactly 60 calendar days after
# window_opens_on."
SEP_WINDOW_DURATION_DAYS: int = 60

# PRD §3.4: "a customer-service operator may appeal the rejected event
# back to SUBMITTED, provided the appeal is filed within 30 calendar days
# of the rejection."
SEP_APPEAL_DAYS: int = 30


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10 results per page, the minimum is 1,
# and the maximum is 100; a request that asks for more than 100 results
# is bounded back to 100. The default offset is 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test default values used by fixtures (NOT PRD-load-bearing).
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "COVERAGE_YEAR": 2026,
    "FILING_STATE": "CA",
    "BASE_PREMIUM_CENTS": 40_000,        # adult age-21 reference premium
    "PRIMARY_FILER_AGE": 35,
    "INSURER_NAME": "Test Insurer",
    "INSURER_PHONE": "+18005551212",
}


__all__ = [
    "FPL_TABLE_V1",
    "FPL_V1_PER_ADDITIONAL",
    "FPL_TABLE_V2",
    "FPL_V2_PER_ADDITIONAL",
    "fpl_denominator",
    "APPLICABLE_PERCENTAGE_TABLE",
    "applicable_fraction",
    "AGE_CURVE",
    "AGE_CURVE_64_PLUS",
    "age_multiplier",
    "TOBACCO_SURCHARGE",
    "CSR_BOUNDARIES",
    "MEDICAID_EXPANSION",
    "GRACE_PERIOD_DAYS",
    "TERMINATION_THRESHOLD_DAYS",
    "SEP_WINDOW_DAYS",
    "SEP_WINDOW_DURATION_DAYS",
    "SEP_APPEAL_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
