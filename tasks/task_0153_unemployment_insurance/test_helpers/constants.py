"""Domain thresholds — numeric constants from PRD calculations and rules.

Each constant traces to a verbatim PRD sentence.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10; clients may supply any integer from
# 1 up to 100 inclusive. The default offset is 0 and must be a non-negative
# integer."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Base-period wage floors — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "if the STANDARD total is at least the base-period wage floor
# of 150,000 cents ($1,500.00), STANDARD is chosen".
MIN_BASE_PERIOD_WAGES_CENTS: int = 150_000

# PRD §3.2: "base_period_total_wages_cents at least 150,000 cents and
# high_quarter_wages_cents at least 90,000 cents".
MIN_HIGH_QUARTER_WAGES_CENTS: int = 90_000


# ---------------------------------------------------------------------------
# Weekly benefit amount — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "The weekly benefit amount in cents is computed by dividing
# high_quarter_wages_cents by 26 with floor (truncating) division, then
# clamping the result to the range from 4,000 cents ($40.00) at the floor
# to 60,000 cents ($600.00) at the ceiling."
WBA_DIVISOR: int = 26
MIN_WBA_CENTS: int = 4_000
MAX_WBA_CENTS: int = 60_000


# ---------------------------------------------------------------------------
# Maximum weeks of eligibility — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "dividing by the product of weekly_benefit_amount_cents and the
# weeks-denominator factor of 3, taking the floor of that quotient, and
# then clamping the result to lie between a minimum of 13 weeks and a
# maximum of 26 weeks inclusive."
WEEKS_DENOMINATOR_FACTOR: int = 3
MIN_REGULAR_WEEKS: int = 13
MAX_REGULAR_WEEKS: int = 26


# ---------------------------------------------------------------------------
# Weekly payable amount — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "take 25% of weekly_benefit_amount_cents and floor the result".
EARNINGS_DISREGARD_PCT: int = 25


# ---------------------------------------------------------------------------
# Work search — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "work_search_count is at least 3 (the minimum required
# work-search contacts)".
MIN_WORK_SEARCH_CONTACTS: int = 3


# ---------------------------------------------------------------------------
# Benefit year — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "sets benefit_year_end to 364 days after benefit_year_start
# (a 52-week benefit year, end-date inclusive)".
BENEFIT_YEAR_DAYS: int = 364


# ---------------------------------------------------------------------------
# Appeal window — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "its deadline_at is computed as filed_at plus the 30-day appeal
# window (APPEAL_WINDOW_DAYS)."
APPEAL_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Statute of limitations — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "the difference between SystemClock.now and the overpayment's
# created_at must be at least 1825 days (a full five years)."
STATUTE_OF_LIMITATIONS_DAYS: int = 1825


# ---------------------------------------------------------------------------
# Experience rate — PRD §3.3, §2.8
# ---------------------------------------------------------------------------
# PRD §3.1: "the persisted experience_rate_bps is bounded between the
# 1.00% floor (100 basis points) and the 5.40% ceiling (540 basis points)."
FLOOR_RATE_BPS: int = 100
CEILING_RATE_BPS: int = 540

# PRD §3.3: tier table — each entry is (lower-bound-inclusive ratio, bps).
EXPERIENCE_RATE_TIERS = [
    (0.10, 100),
    (0.07, 180),
    (0.04, 270),
    (0.01, 380),
    (0.00, 460),
]
# PRD §3.3: "a strictly negative reserve ratio yields the 5.40% ceiling
# of 540 basis points."
NEGATIVE_RATIO_BPS: int = 540


# ---------------------------------------------------------------------------
# Pandemic extension — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "assigning a program_name ... an effective_start and effective_end
# date pair, and an extra_weeks count between 1 and 26 inclusive".
MIN_EXTRA_WEEKS: int = 1
MAX_EXTRA_WEEKS: int = 26


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "claimant_full_name": "Test Claimant",
    "claimant_state": "CA",
    "claimant_dob": "1985-06-15",
    "ssn_last4_prefix": "9",  # generate as random 4-digit string
    "employer_legal_name": "Test Employer LLC",
    # PRD §3.1: "reserve_ratio_basis_cents ... must be strictly greater than
    # zero". A million-cent ($10,000) reserve over a $100,000 payroll gives
    # exactly the 0.10 floor tier (100 bps).
    "employer_reserve_basis": 1_000_000,
    "employer_taxable_payroll": 10_000_000,
    "pandemic_program_name": "Test PEUC",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "MIN_BASE_PERIOD_WAGES_CENTS",
    "MIN_HIGH_QUARTER_WAGES_CENTS",
    "WBA_DIVISOR",
    "MIN_WBA_CENTS",
    "MAX_WBA_CENTS",
    "WEEKS_DENOMINATOR_FACTOR",
    "MIN_REGULAR_WEEKS",
    "MAX_REGULAR_WEEKS",
    "EARNINGS_DISREGARD_PCT",
    "MIN_WORK_SEARCH_CONTACTS",
    "BENEFIT_YEAR_DAYS",
    "APPEAL_WINDOW_DAYS",
    "STATUTE_OF_LIMITATIONS_DAYS",
    "FLOOR_RATE_BPS",
    "CEILING_RATE_BPS",
    "EXPERIENCE_RATE_TIERS",
    "NEGATIVE_RATIO_BPS",
    "MIN_EXTRA_WEEKS",
    "MAX_EXTRA_WEEKS",
    "TEST_DEFAULTS",
]
