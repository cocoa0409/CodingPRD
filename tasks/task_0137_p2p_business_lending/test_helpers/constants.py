"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Platform defaults — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "origination_fee_bps defaults to 300".
DEFAULT_ORIGINATION_FEE_BPS: int = 300

# PRD §3.1: "servicing_fee_bps defaults to 100".
DEFAULT_SERVICING_FEE_BPS: int = 100

# PRD §3.1: "late_fee_cents defaults to 2500".
DEFAULT_LATE_FEE_CENTS: int = 2500

# PRD §3.1: "max_borrower_concentration_bps defaults to 1000, which caps
# any one investor's exposure to any one borrower at ten percent of that
# investor's committed capital."
DEFAULT_MAX_BORROWER_CONCENTRATION_BPS: int = 1000

# PRD §3.1: "an optional ISO-4217 currency (defaulting to 'USD')".
DEFAULT_CURRENCY: str = "USD"


# ---------------------------------------------------------------------------
# Investment denomination — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The pledge's denomination must be at least 2,500 cents and
# a positive integer multiple of 100 cents".
INVESTMENT_MIN_CENTS: int = 2500
INVESTMENT_MULTIPLE_CENTS: int = 100


# ---------------------------------------------------------------------------
# Tiered interest rate — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The base table is exactly { A: 600, B: 900, C: 1300,
# D: 1800, E: 2400 }".
BASE_RATE_BPS_BY_GRADE = {
    "A": 600,
    "B": 900,
    "C": 1300,
    "D": 1800,
    "E": 2400,
}

# PRD §3.3: "the term premium is computed as the maximum of zero and
# the term in months minus 24, then multiplied by ten basis points per
# month".
TERM_PREMIUM_BPS_PER_MONTH_OVER_24: int = 10
TERM_PREMIUM_BASE_MONTHS: int = 24


# ---------------------------------------------------------------------------
# Loan term — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The term must be exactly 12, 24, 36, 48, or 60 months."
ALLOWED_TERM_MONTHS = [12, 24, 36, 48, 60]


# ---------------------------------------------------------------------------
# Listing funding deadline — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "sets funding_deadline_day_index to the platform's current
# clock_day_index plus 14".
FUNDING_DEADLINE_OFFSET_DAYS: int = 14


# ---------------------------------------------------------------------------
# Installment due / grace — PRD §3.4, §3.6
# ---------------------------------------------------------------------------
# PRD §3.4: "due_day_index set to origination_day_index plus
# sequence_number multiplied by 30".
INSTALLMENT_PERIOD_DAYS: int = 30

# PRD §3.6: "the platform's clock_day_index is strictly greater than
# due_day_index plus a five-day grace".
INSTALLMENT_GRACE_DAYS: int = 5


# ---------------------------------------------------------------------------
# Loan delinquency thresholds — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "When consecutive_missed_installments reaches three or more,
# the loan transitions DELINQUENT → DEFAULT during the same sweep".
DEFAULT_THRESHOLD_MISSED: int = 3

# PRD §3.6: "When the counter reaches five or more, the loan transitions
# DEFAULT → CHARGED_OFF".
CHARGE_OFF_THRESHOLD_MISSED: int = 5


# ---------------------------------------------------------------------------
# Provisional grade bands — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2 provisional and final grade thresholds: "0.80 or higher is A,
# 0.65 up to but not including 0.80 is B, 0.50 up to 0.65 is C, 0.35 up
# to 0.50 is D, and any score below 0.35 is E."
GRADE_BAND_A: float = 0.80
GRADE_BAND_B: float = 0.65
GRADE_BAND_C: float = 0.50
GRADE_BAND_D: float = 0.35


# ---------------------------------------------------------------------------
# Provisional-grade normalization clamps — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "Annual revenue is normalized linearly from a floor of
# 50,000 dollars (5,000,000 cents) to a ceiling of 5,000,000 dollars
# (500,000,000 cents)".
PROV_REVENUE_FLOOR_CENTS: int = 5_000_000
PROV_REVENUE_CEILING_CENTS: int = 500_000_000

# PRD §3.2: "The requested amount is normalized linearly from a floor of
# 10,000 dollars (1,000,000 cents) to a ceiling of 500,000 dollars
# (50,000,000 cents)".
PROV_REQUESTED_FLOOR_CENTS: int = 1_000_000
PROV_REQUESTED_CEILING_CENTS: int = 50_000_000


# ---------------------------------------------------------------------------
# Final-grade clamps — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "deposits_last_90d_cents divided by 90, then clamped to lie
# between 0 and 10,000,000 cents".
FINAL_CASHFLOW_CLAMP_CENTS: int = 10_000_000

# PRD §3.2: "avg_daily_balance_cents clamped between 0 and 25,000,000
# cents".
FINAL_RESERVES_CLAMP_CENTS: int = 25_000_000

# PRD §3.2: "The NSF penalty is nsf_count_last_90d multiplied by 0.10
# and clamped between 0 and 0.50".
FINAL_NSF_PENALTY_PER_NSF: float = 0.10
FINAL_NSF_PENALTY_CAP: float = 0.50


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10 with a minimum of 1 and a maximum of
# 100, and offset defaults to 0".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test default money values — anchored to scenario examples in PRD prose.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PLATFORM_NAME": "Test P2P Platform",
    "PRINCIPAL_CENTS": 100_000,
    "TERM_MONTHS": 12,
    "INVESTOR_COMMITTED_CAPITAL_CENTS": 10_000_00,  # $10,000
    "INVESTOR_DEPOSIT_CENTS": 10_000_00,
    "BORROWER_ANNUAL_REVENUE_CENTS": 1_000_000_00,  # $1,000,000
    "BORROWER_REQUESTED_AMOUNT_CENTS": 100_000_00,  # $100,000
    "PLAID_DEPOSITS_LAST_90D_CENTS": 15_000_00,
    "PLAID_AVG_DAILY_BALANCE_CENTS": 2_000_00,
    "PLAID_NSF_COUNT": 3,
    "PLAID_DEBT_SERVICE_CENTS": 2_000_00,
}


__all__ = [
    "DEFAULT_ORIGINATION_FEE_BPS",
    "DEFAULT_SERVICING_FEE_BPS",
    "DEFAULT_LATE_FEE_CENTS",
    "DEFAULT_MAX_BORROWER_CONCENTRATION_BPS",
    "DEFAULT_CURRENCY",
    "INVESTMENT_MIN_CENTS",
    "INVESTMENT_MULTIPLE_CENTS",
    "BASE_RATE_BPS_BY_GRADE",
    "TERM_PREMIUM_BPS_PER_MONTH_OVER_24",
    "TERM_PREMIUM_BASE_MONTHS",
    "ALLOWED_TERM_MONTHS",
    "FUNDING_DEADLINE_OFFSET_DAYS",
    "INSTALLMENT_PERIOD_DAYS",
    "INSTALLMENT_GRACE_DAYS",
    "DEFAULT_THRESHOLD_MISSED",
    "CHARGE_OFF_THRESHOLD_MISSED",
    "GRADE_BAND_A",
    "GRADE_BAND_B",
    "GRADE_BAND_C",
    "GRADE_BAND_D",
    "PROV_REVENUE_FLOOR_CENTS",
    "PROV_REVENUE_CEILING_CENTS",
    "PROV_REQUESTED_FLOOR_CENTS",
    "PROV_REQUESTED_CEILING_CENTS",
    "FINAL_CASHFLOW_CLAMP_CENTS",
    "FINAL_RESERVES_CLAMP_CENTS",
    "FINAL_NSF_PENALTY_PER_NSF",
    "FINAL_NSF_PENALTY_CAP",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
