"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Risk-score bucket boundaries — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a raw score of ten or less assigns CONSERVATIVE; a raw
# score from eleven through seventeen assigns MODERATE; a raw score of
# eighteen or greater (and no higher than the maximum twenty-five)
# assigns AGGRESSIVE."
CONSERVATIVE_MAX: int = 10
MODERATE_MAX: int = 17
AGGRESSIVE_MAX: int = 25

# PRD §3.1: "the variant uses the same formula except that the third term
# — the growth-vs-stability contribution — is replaced by one times the
# quantity six minus q3_growth_vs_stability, inverting the growth axis so
# that a higher growth preference for an older client lowers the raw
# score and biases the bucket toward stability." Age threshold:
# PRD §3.1: "the client's derived age is at least fifty-five years (the
# age-bias threshold)".
AGE_BIAS_THRESHOLD: int = 55


# ---------------------------------------------------------------------------
# Time horizon bands — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "SHORT covers years one through five, MID covers years six
# through fifteen, and LONG covers years sixteen through forty."
HORIZON_SHORT_MAX: int = 5
HORIZON_MID_MAX: int = 15
HORIZON_LONG_MAX: int = 40

# PRD §3.1: "time_horizon_years value must be at least one and at most
# forty".
TIME_HORIZON_MIN: int = 1
TIME_HORIZON_MAX: int = 40


# ---------------------------------------------------------------------------
# Drift trigger threshold — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "a non-force start requires max_drift_pct to be at least 5.00
# percentage points". PRD §3.8: "The drift threshold of five percentage
# points is the only constant in this gate."
DRIFT_TRIGGER_PCT: float = 5.00


# ---------------------------------------------------------------------------
# Harvest threshold — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "When the unrealized P&L is at most negative five hundred
# dollars — that is, unrealized_loss_cents is less than or equal to
# negative fifty thousand cents, with the boundary inclusive — the
# system creates a new HarvestOpportunity row in DETECTED".
# PRD §3.7: "The five-hundred-dollar minimum harvest threshold is the
# only constant in this rule."
MIN_HARVEST_THRESHOLD_CENTS: int = 50_000


# ---------------------------------------------------------------------------
# Wash sale window — PRD §3.6 / §2.10
# ---------------------------------------------------------------------------
# PRD §2.10: "The wash sale window is symmetric and inclusive: thirty
# calendar days before through thirty calendar days after the calendar
# date of the realized loss". PRD §3.6: "The thirty-day window length is
# the only constant in this rule."
WASH_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# 1099-B holding-period threshold — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "A trade is classified SHORT when its weighted holding
# period is at most three hundred and sixty-five days and LONG when it
# exceeds three hundred and sixty-five days. The three-hundred-and-
# sixty-five-day long-term threshold is the only constant in this rule."
LONG_TERM_DAY_THRESHOLD: int = 365


# ---------------------------------------------------------------------------
# 1099-B post-issue void window — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "a void from ISSUED to VOIDED is permitted only when the
# form was issued less than thirty calendar days ago".
ISSUED_VOID_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Fractional share precision — PRD §2.8
# ---------------------------------------------------------------------------
# PRD §2.8: "Fractional share quantities — produced only by the dividend
# reinvestment path — are truncated to four decimal places."
FRACTIONAL_SHARE_DECIMALS: int = 4


# ---------------------------------------------------------------------------
# Validation bounds — PRD §3.1 / §3.2 / §3.9
# ---------------------------------------------------------------------------
# PRD §3.1: "Each of the five integer answers ... must be an integer in
# the inclusive range one through five."
QUESTIONNAIRE_MIN: int = 1
QUESTIONNAIRE_MAX: int = 5

# PRD §3.2: "The allocation is a mapping from asset class to a decimal
# weight between zero and one inclusive, and the five weights must sum to
# exactly one."
ALLOCATION_MIN: float = 0.0
ALLOCATION_MAX: float = 1.0
ALLOCATION_SUM: float = 1.0

# PRD §3.9: "a correlation value in the inclusive interval from negative
# one through positive one".
CORRELATION_MIN: float = -1.0
CORRELATION_MAX: float = 1.0


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10 when omitted, the minimum is 1, and
# the maximum is 100. The default offset is 0 and it must be a
# non-negative integer."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Full-name length — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "their legal full_name (between one and one hundred twenty
# characters)".
FULL_NAME_MIN_LEN: int = 1
FULL_NAME_MAX_LEN: int = 120


# ---------------------------------------------------------------------------
# Asset-class list — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the five fixed asset classes — US_EQUITY, INTL_EQUITY,
# US_BOND, INTL_BOND, CASH".
ASSET_CLASSES = ["US_EQUITY", "INTL_EQUITY", "US_BOND", "INTL_BOND", "CASH"]


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values for reuse.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "FULL_NAME": "Test Client",
    "BIRTH_DATE": "1980-01-01",
    "TIME_HORIZON_YEARS": 20,
    "ACCOUNT_FUNDING_CENTS": 1_000_000,  # $10,000.
    "SECURITY_PRICE_CENTS": 10_000,  # $100.00.
    "MODEL_ALLOCATION": {
        "US_EQUITY": 0.60,
        "INTL_EQUITY": 0.20,
        "US_BOND": 0.15,
        "INTL_BOND": 0.04,
        "CASH": 0.01,
    },
}


__all__ = [
    "CONSERVATIVE_MAX",
    "MODERATE_MAX",
    "AGGRESSIVE_MAX",
    "AGE_BIAS_THRESHOLD",
    "HORIZON_SHORT_MAX",
    "HORIZON_MID_MAX",
    "HORIZON_LONG_MAX",
    "TIME_HORIZON_MIN",
    "TIME_HORIZON_MAX",
    "DRIFT_TRIGGER_PCT",
    "MIN_HARVEST_THRESHOLD_CENTS",
    "WASH_WINDOW_DAYS",
    "LONG_TERM_DAY_THRESHOLD",
    "ISSUED_VOID_WINDOW_DAYS",
    "FRACTIONAL_SHARE_DECIMALS",
    "QUESTIONNAIRE_MIN",
    "QUESTIONNAIRE_MAX",
    "ALLOCATION_MIN",
    "ALLOCATION_MAX",
    "ALLOCATION_SUM",
    "CORRELATION_MIN",
    "CORRELATION_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "FULL_NAME_MIN_LEN",
    "FULL_NAME_MAX_LEN",
    "ASSET_CLASSES",
    "TEST_DEFAULTS",
]
