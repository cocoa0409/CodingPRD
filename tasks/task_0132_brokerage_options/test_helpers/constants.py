"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Options eligibility tiers — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "Level 1 (covered calls and cash-secured puts) requires years
# at least 0 and liquid_net_worth_cents at least 1,000,000 — that is, at
# least ten thousand dollars of liquid net worth."
LEVEL_1_YRS: int = 0
LEVEL_1_LNW_CENTS: int = 1_000_000

# PRD §3.2: "Level 2 (long calls and long puts) additionally requires
# years at least 1 and liquid_net_worth_cents at least 5,000,000 — fifty
# thousand dollars liquid."
LEVEL_2_YRS: int = 1
LEVEL_2_LNW_CENTS: int = 5_000_000

# PRD §3.2: "Level 3 (spreads) additionally requires years at least 2
# with liquid_net_worth_cents at least 10,000,000 and total_net_worth_cents
# at least 25,000,000 — a hundred thousand dollars liquid and a quarter
# million dollars total."
LEVEL_3_YRS: int = 2
LEVEL_3_LNW_CENTS: int = 10_000_000
LEVEL_3_TNW_CENTS: int = 25_000_000

# PRD §3.2: "Level 4 (uncovered / naked options) additionally requires
# years at least 3 with liquid_net_worth_cents at least 25,000,000 and
# total_net_worth_cents at least 50,000,000 — a quarter million dollars
# liquid and half a million dollars total."
LEVEL_4_YRS: int = 3
LEVEL_4_LNW_CENTS: int = 25_000_000
LEVEL_4_TNW_CENTS: int = 50_000_000


# ---------------------------------------------------------------------------
# Options-strategy → required account.options_level — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "COVERED_CALL and CASH_SECURED_PUT require an options_level
# of at least 1; LONG_CALL and LONG_PUT require at least 2; SPREAD
# requires at least 3; NAKED_CALL and NAKED_PUT require at least 4."
STRATEGY_TO_REQUIRED_LEVEL = {
    "COVERED_CALL": 1,
    "CASH_SECURED_PUT": 1,
    "LONG_CALL": 2,
    "LONG_PUT": 2,
    "SPREAD": 3,
    "NAKED_CALL": 4,
    "NAKED_PUT": 4,
}


# ---------------------------------------------------------------------------
# Margin requirement rates — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3 (Reg T): "the base is the notional multiplied by 0.50 and
# rounded up to the next whole cent."
REG_T_RATE: float = 0.50

# PRD §3.3 (PMA): "the base is the notional multiplied by 0.15 and
# rounded up to the next whole cent — strictly lower than the Reg T
# figure on identical inputs".
PMA_RATE: float = 0.15

# PRD §3.3 (CASH): "For a CASH account, the base equals the full notional
# — 100% of the trade must be available in cash."
CASH_RATE: float = 1.00

# PRD §3.3: "an additional 20% of notional, rounded up to the next whole
# cent, is added to the base." (Reg T naked option add-on.)
NAKED_ADDON_RATE: float = 0.20


# ---------------------------------------------------------------------------
# Pattern Day Trader — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "If the count is at least 4 and Account.equity_value_cents
# is strictly less than 2,500,000 (the equivalent of twenty-five thousand
# US dollars), the Pattern Day Trader threshold has tripped".
PDT_TRADE_THRESHOLD: int = 4
PDT_EQUITY_FLOOR_CENTS: int = 2_500_000

# PRD §3.4: "a rolling window of five business days inclusive of both
# endpoints — the window starts four business days before today's UTC
# date and ends today, so a trade on either boundary date counts."
PDT_WINDOW_BUSINESS_DAYS: int = 5


# ---------------------------------------------------------------------------
# ACAT transfer — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "starting from the calendar date of initiated_at, add one
# calendar day at a time and decrement a remaining counter each time the
# new date is a Monday, Tuesday, Wednesday, Thursday, or Friday; stop
# when the counter reaches 0, having consumed exactly 6 business days.
# The resulting date is then pinned to 17:00:00 UTC".
ACAT_BUSINESS_DAYS: int = 6
ACAT_COMPLETION_HOUR_UTC: int = 17

# PRD §3.5: "a minimum of 100 cents (one dollar) is enforced".
ACAT_MIN_VALUE_CENTS: int = 100


# ---------------------------------------------------------------------------
# OptionsApproval revision bound — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "is permitted only while revision_count is strictly less than
# 3; at the boundary of 3 the action is rejected with
# ERR_REVISION_LIMIT_REACHED at HTTP 409."
REVISION_LIMIT: int = 3


# ---------------------------------------------------------------------------
# Customer input constraints — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "legal_name (1 to 120 characters)".
LEGAL_NAME_MIN_LEN: int = 1
LEGAL_NAME_MAX_LEN: int = 120

# PRD §3.1: "ssn_last4 (exactly four digits, immutable once first
# persisted)".
SSN_LAST4_LEN: int = 4


# ---------------------------------------------------------------------------
# KYC age threshold — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "the customer's age, derived from date_of_birth, must be at
# least 18 years at the moment of submission".
KYC_MIN_AGE_YEARS: int = 18


# ---------------------------------------------------------------------------
# Order field constraints — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "symbol (uppercase A–Z, 1 to 5 characters)".
SYMBOL_MIN_LEN: int = 1
SYMBOL_MAX_LEN: int = 5

# PRD §3.3: "an integer quantity of at least 1".
ORDER_MIN_QUANTITY: int = 1


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default value of limit is 10, its minimum is 1, and its
# maximum is 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — sensible values anchored to PRD prose
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # Customer defaults — VERIFIED-able, options-level-4-eligible by
    # default (yrs=5, lnw=$1M cents=100_000_000, tnw=$2M cents=200_000_000).
    "LEGAL_NAME": "Jane Q Customer",
    "DATE_OF_BIRTH": "1985-06-15",  # over 18
    "SSN_LAST4": "1234",
    "ANNUAL_INCOME_CENTS": 30_000_000,         # $300k
    "LIQUID_NET_WORTH_CENTS": 100_000_000,     # $1M
    "TOTAL_NET_WORTH_CENTS": 200_000_000,      # $2M
    "YEARS_OPTIONS_EXPERIENCE": 5,
    # KYC submission defaults.
    "GOVERNMENT_ID_TYPE": "PASSPORT",
    "GOVERNMENT_ID_NUMBER": "X1234567",
    "ADDRESS_LINE1": "123 Main St",
    "ADDRESS_COUNTRY": "US",
    # Cash defaults for funded accounts.
    "CASH_BALANCE_CENTS": 10_000_000,          # $100k via INBOUND ACAT
    # Order defaults.
    "SYMBOL_AAPL": "AAPL",
    "DEFAULT_LIMIT_PRICE_CENTS": 15_000,       # $150
}


__all__ = [
    "LEVEL_1_YRS",
    "LEVEL_1_LNW_CENTS",
    "LEVEL_2_YRS",
    "LEVEL_2_LNW_CENTS",
    "LEVEL_3_YRS",
    "LEVEL_3_LNW_CENTS",
    "LEVEL_3_TNW_CENTS",
    "LEVEL_4_YRS",
    "LEVEL_4_LNW_CENTS",
    "LEVEL_4_TNW_CENTS",
    "STRATEGY_TO_REQUIRED_LEVEL",
    "REG_T_RATE",
    "PMA_RATE",
    "CASH_RATE",
    "NAKED_ADDON_RATE",
    "PDT_TRADE_THRESHOLD",
    "PDT_EQUITY_FLOOR_CENTS",
    "PDT_WINDOW_BUSINESS_DAYS",
    "ACAT_BUSINESS_DAYS",
    "ACAT_COMPLETION_HOUR_UTC",
    "ACAT_MIN_VALUE_CENTS",
    "REVISION_LIMIT",
    "LEGAL_NAME_MIN_LEN",
    "LEGAL_NAME_MAX_LEN",
    "SSN_LAST4_LEN",
    "KYC_MIN_AGE_YEARS",
    "SYMBOL_MIN_LEN",
    "SYMBOL_MAX_LEN",
    "ORDER_MIN_QUANTITY",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
