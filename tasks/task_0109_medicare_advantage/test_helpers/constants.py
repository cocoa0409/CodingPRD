"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# IEP window calculation — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "iep_start_date is the first day of the month that falls
# three months before medicare_eligibility_date, and iep_end_date is the
# last second of the month that falls three months after
# medicare_eligibility_date — i.e., 23:59:59 UTC on the final day of
# that month, inclusive."
IEP_PRE_MONTHS: int = 3
IEP_POST_MONTHS: int = 3
# PRD §3.1: "Otherwise (the standard age-65 pathway), eligibility begins
# on the first day of the month that contains date_of_birth plus
# sixty-five years."
MEDICARE_AGE_YEARS: int = 65
# PRD §3.1: "if has_disability is true and ssdi_start_date is set,
# eligibility begins on the first day of the month that contains
# ssdi_start_date plus twenty-four months."
SSDI_WAIT_MONTHS: int = 24
# PRD §3.5: derivable from "the count of whole months between
# medicare_eligibility_date and effective_date minus seven (the
# seven-month IEP grace)".
IEP_GRACE_MONTHS: int = 7


# ---------------------------------------------------------------------------
# Late Enrollment Penalty constants — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "the national-average Part B premium (a fixed constant equal
# to seventeen thousand four hundred ninety cents, i.e. $174.90)".
NATIONAL_AVG_PART_B_PREMIUM_CENTS: int = 17_490

# PRD §3.5: "the national-average Part D base-beneficiary-premium
# constant (three thousand six hundred seventy-eight cents, i.e. $36.78)".
NATIONAL_AVG_PART_D_BASE_PREMIUM_CENTS: int = 3_678

# PRD §3.5: "ten percent of a national-average Part B premium constant,
# applied once for every full twelve-month block".
LEP_PART_B_PER_YEAR_DECIMAL: float = 0.10

# PRD §3.5: "The penalty_rate_decimal is months_late multiplied by
# 0.01 (so eleven months produces 0.11, twelve produces 0.12, thirteen
# produces 0.13)."
LEP_PART_D_PER_MONTH_DECIMAL: float = 0.01


# ---------------------------------------------------------------------------
# Donut hole copay & gap/catastrophic rates — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "The five copay rates are 5% for TIER_1, 15% for TIER_2,
# 25% for TIER_3, 40% for TIER_4, and 50% for TIER_5."
COPAY_RATE_INITIAL: dict = {
    "TIER_1": 0.05,
    "TIER_2": 0.15,
    "TIER_3": 0.25,
    "TIER_4": 0.40,
    "TIER_5": 0.50,
}

# PRD §3.8: "the covered amount multiplied by 0.25 (the gap rate — the
# beneficiary pays twenty-five percent in the gap)".
GAP_RATE: float = 0.25

# PRD §3.8: "the remainder multiplied by 0.05 (the catastrophic rate —
# five percent)".
CATASTROPHIC_RATE: float = 0.05


# ---------------------------------------------------------------------------
# Star-rating weights & banding — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "fifty percent of the clinical-quality score plus thirty
# percent of the member-experience score plus twenty percent of the
# customer-service score (the three weights sum to one)".
W_CLINICAL: float = 0.50
W_EXPERIENCE: float = 0.30
W_SERVICE: float = 0.20

# PRD §3.3: "a composite of 90 or higher maps to 5.0; from 80 up to but
# excluding 90 maps to 4.5; from 70 up to but excluding 80 maps to 4.0;
# from 60 up to but excluding 70 maps to 3.5; from 50 up to but
# excluding 60 maps to 3.0; from 40 up to but excluding 50 maps to 2.5;
# from 30 up to but excluding 40 maps to 2.0; from 20 up to but
# excluding 30 maps to 1.5; and anything below 20 maps to 1.0."
STAR_BANDS: list = [
    (90.0, 5.0),
    (80.0, 4.5),
    (70.0, 4.0),
    (60.0, 3.5),
    (50.0, 3.0),
    (40.0, 2.5),
    (30.0, 2.0),
    (20.0, 1.5),
    (0.0, 1.0),
]


# ---------------------------------------------------------------------------
# Plan field bounds — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "plan_year (a four-digit year between 2020 and 2030
# inclusive)".
PLAN_YEAR_MIN: int = 2020
PLAN_YEAR_MAX: int = 2030


# ---------------------------------------------------------------------------
# SEP loss-of-coverage window — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §3.9: "opens a fresh SEP_LOSS_OF_COVERAGE EnrollmentPeriod for the
# beneficiary whose window_start is the current clock day and whose
# window_end is the current clock day plus sixty-three days".
SEP_LOSS_OF_COVERAGE_DURATION_DAYS: int = 63


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10, has a minimum of 1, and a maximum of
# 100; values outside this band are rejected with ERR_VALIDATION.
# offset defaults to 0 and may be any non-negative integer."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PARTB_PREMIUM_CENTS": 18_000,
    "PARTD_PREMIUM_CENTS": 4_000,
    "PARTC_PREMIUM_CENTS": 12_000,
    "MEDIGAP_PREMIUM_CENTS": 20_000,
    # PRD §3.8: D = annual_deductible_cents, I = initial_coverage_limit_cents,
    # C = catastrophic_threshold_cents — values used in test scaffolding.
    "PARTD_DEDUCTIBLE_CENTS": 40_000,
    "PARTD_INITIAL_LIMIT_CENTS": 400_000,
    "PARTD_CATASTROPHIC_CENTS": 150_000,
    # Default state code for residency and Medigap matching.
    "STATE_CODE": "CA",
    # PRD §3.3: star_rating step 0.5.
    "STAR_RATING_DEFAULT": 4.0,
}


__all__ = [
    "IEP_PRE_MONTHS",
    "IEP_POST_MONTHS",
    "MEDICARE_AGE_YEARS",
    "SSDI_WAIT_MONTHS",
    "IEP_GRACE_MONTHS",
    "NATIONAL_AVG_PART_B_PREMIUM_CENTS",
    "NATIONAL_AVG_PART_D_BASE_PREMIUM_CENTS",
    "LEP_PART_B_PER_YEAR_DECIMAL",
    "LEP_PART_D_PER_MONTH_DECIMAL",
    "COPAY_RATE_INITIAL",
    "GAP_RATE",
    "CATASTROPHIC_RATE",
    "W_CLINICAL",
    "W_EXPERIENCE",
    "W_SERVICE",
    "STAR_BANDS",
    "PLAN_YEAR_MIN",
    "PLAN_YEAR_MAX",
    "SEP_LOSS_OF_COVERAGE_DURATION_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
