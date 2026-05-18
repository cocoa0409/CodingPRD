"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md so tests
have a single source of truth for boundaries.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Time windows — PRD §3.2, §3.7, §3.8, §3.9
# ---------------------------------------------------------------------------
# PRD §3.2: "computes draw_period_end_date as exactly 3650 days (ten
# years) after origination_date".
DRAW_PERIOD_DAYS: int = 3650

# PRD §3.7: "advances every HELOC currently in DRAW or REPAY by one
# 30-day cycle".
DAYS_PER_CYCLE: int = 30

# PRD §3.7: "divided by 30 to convert to a monthly rate" / "30 (one
# cycle's days) and divided by 365 (the canonical accrual year)".
DAYS_PER_YEAR_ACCRUAL: int = 365

# PRD §3.7: "if delinquency_days is at least 90 ... the system records a
# DefaultEvent with trigger of DELINQUENCY_90".
DELINQUENCY_DEFAULT_DAYS: int = 90

# PRD §3.8: "current clock time has reached or passed origination_date
# plus 365 days times the anniversary index".
ANNIVERSARY_DAYS: int = 365

# PRD §3.9: "If that tenure is strictly less than 1095 days (three
# years) and the HELOC's early_closure_fee_cents is strictly greater
# than zero".
EARLY_CLOSURE_WINDOW_DAYS: int = 1095

# PRD §3.4 amortization: canonical 30-day month and 12 months in a year.
MONTHS_PER_YEAR: int = 12
DAYS_PER_AMORT_MONTH: int = 30


# ---------------------------------------------------------------------------
# Heloc configuration bounds — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "a credit_limit_cents between 1000000 and 50000000".
MIN_CREDIT_LIMIT_CENTS: int = 1_000_000
MAX_CREDIT_LIMIT_CENTS: int = 50_000_000

# PRD §3.2: "a margin_bps between 0 and 1000 inclusive".
MIN_MARGIN_BPS: int = 0
MAX_MARGIN_BPS: int = 1_000

# PRD §3.2: "a periodic_cap_bps greater than 0 and at most 500".
MIN_PERIODIC_CAP_BPS_EXCLUSIVE: int = 0
MAX_PERIODIC_CAP_BPS: int = 500

# PRD §3.2: "a lifetime_cap_bps that must be strictly greater than
# initial_rate_bps + periodic_cap_bps and at most 2500".
MAX_LIFETIME_CAP_BPS: int = 2_500

# PRD §3.2: "a repayment_term_years between 10 and 20 inclusive".
MIN_REPAY_TERM_YEARS: int = 10
MAX_REPAY_TERM_YEARS: int = 20

# PRD §3.2: "an annual_fee_cents between 0 and 25000 inclusive".
MIN_ANNUAL_FEE_CENTS: int = 0
MAX_ANNUAL_FEE_CENTS: int = 25_000

# PRD §3.2: "an early_closure_fee_cents between 0 and 50000 inclusive".
MIN_EARLY_CLOSURE_FEE_CENTS: int = 0
MAX_EARLY_CLOSURE_FEE_CENTS: int = 50_000

# PRD §3.5: "a quoted prime_rate_bps between 0 and 3000 inclusive".
MAX_PRIME_RATE_BPS: int = 3_000


# ---------------------------------------------------------------------------
# Property / SeniorLien bounds — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "an appraised_value_cents of at least 100000 (one thousand
# dollars in cents)".
MIN_APPRAISED_VALUE_CENTS: int = 100_000

# PRD §3.1: "an address between 1 and 300 characters".
ADDRESS_MAX_LEN: int = 300

# PRD §3.1: "a full_name between 1 and 200 characters".
FULL_NAME_MAX_LEN: int = 200

# PRD §3.1: "holder_name (1 to 200 characters, informational)".
HOLDER_NAME_MAX_LEN: int = 200


# ---------------------------------------------------------------------------
# Draws — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "an amount_cents of at least 10000 (one hundred dollars)".
MIN_DRAW_AMOUNT_CENTS: int = 10_000


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "if omitted it defaults to 10, with a minimum of 1 and a
# maximum of 100".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Convenient time conversion
# ---------------------------------------------------------------------------
SECONDS_PER_DAY: int = 86_400


# ---------------------------------------------------------------------------
# Test default values used across factories / fixtures
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "APPRAISED_VALUE_CENTS": 50_000_000,
    "SENIOR_LIEN_PRINCIPAL_CENTS": 10_000_000,
    "CREDIT_LIMIT_CENTS": 2_000_000,
    "MARGIN_BPS": 300,
    "PERIODIC_CAP_BPS": 200,
    "LIFETIME_CAP_BPS": 2_000,
    "LIFETIME_FLOOR_BPS": 100,
    "REPAYMENT_TERM_YEARS": 10,
    "ANNUAL_FEE_CENTS": 5_000,
    "EARLY_CLOSURE_FEE_CENTS": 10_000,
    "PRIME_RATE_BPS_AT_ORIGINATION": 500,  # current_rate_bps = 800
}


__all__ = [
    "DRAW_PERIOD_DAYS",
    "DAYS_PER_CYCLE",
    "DAYS_PER_YEAR_ACCRUAL",
    "DELINQUENCY_DEFAULT_DAYS",
    "ANNIVERSARY_DAYS",
    "EARLY_CLOSURE_WINDOW_DAYS",
    "MONTHS_PER_YEAR",
    "DAYS_PER_AMORT_MONTH",
    "MIN_CREDIT_LIMIT_CENTS",
    "MAX_CREDIT_LIMIT_CENTS",
    "MIN_MARGIN_BPS",
    "MAX_MARGIN_BPS",
    "MIN_PERIODIC_CAP_BPS_EXCLUSIVE",
    "MAX_PERIODIC_CAP_BPS",
    "MAX_LIFETIME_CAP_BPS",
    "MIN_REPAY_TERM_YEARS",
    "MAX_REPAY_TERM_YEARS",
    "MIN_ANNUAL_FEE_CENTS",
    "MAX_ANNUAL_FEE_CENTS",
    "MIN_EARLY_CLOSURE_FEE_CENTS",
    "MAX_EARLY_CLOSURE_FEE_CENTS",
    "MAX_PRIME_RATE_BPS",
    "MIN_APPRAISED_VALUE_CENTS",
    "ADDRESS_MAX_LEN",
    "FULL_NAME_MAX_LEN",
    "HOLDER_NAME_MAX_LEN",
    "MIN_DRAW_AMOUNT_CENTS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SECONDS_PER_DAY",
    "TEST_DEFAULTS",
]
