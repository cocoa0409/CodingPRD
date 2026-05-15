"""Domain thresholds — numeric constants from PRD calculations.

These constants are derived from the verbatim numerical thresholds the
PRD calls out in §2.3, §2.4, §3.3, §3.5, §3.6, §3.7, §3.8, §3.9, §3.10.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Auction / ranking — PRD §3.5
# ---------------------------------------------------------------------------
MIN_QUALITY_SCORE = 1.0
MAX_QUALITY_SCORE = 10.0
MIN_PREDICTED_CTR = 0.0
MAX_PREDICTED_CTR = 1.0
DEFAULT_QUALITY_SCORE = 5.0
DEFAULT_PREDICTED_CTR = 0.02
SHADING_FACTOR = 0.92  # PRD §3.5 — applied only on EXTERNAL_RTB + GSP

# IVT threshold — PRD §3.6: "When ivt_score is strictly greater than
# 0.7, the event transitions to INVALID_TRAFFIC ... when ivt_score is at
# most 0.7, the event transitions to VALID."
IVT_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Pre-screen score bands — PRD §3.4
# ---------------------------------------------------------------------------
# "If pre_screen_score is at least 0.8, the creative moves to
# PRESCREEN_FAILED ... If pre_screen_score is strictly less than 0.5,
# the creative moves to PENDING_HUMAN_REVIEW ... If pre_screen_score is
# in the half-open interval starting at 0.5 inclusive and ending at 0.8
# exclusive — the borderline band ..."
PRESCREEN_FAIL_THRESHOLD = 0.8       # >= 0.8 -> PRESCREEN_FAILED
PRESCREEN_BORDERLINE_FLOOR = 0.5     # [0.5, 0.8) borderline


# ---------------------------------------------------------------------------
# Budget — PRD §3.3
# ---------------------------------------------------------------------------
MIN_DAILY_BUDGET_CENTS = 100  # PRD §3.3: "daily_budget_cents must be at least 100 (one dollar in cents)"


# ---------------------------------------------------------------------------
# Wallet — PRD §3.1
# ---------------------------------------------------------------------------
DEFAULT_LOW_BALANCE_THRESHOLD_CENTS = 10000  # PRD §3.1: defaults to 10000
DEFAULT_CREDIT_LINE_CENTS = 0  # PRD §3.1: defaults to 0
DEFAULT_TAX_RATE_BPS = 0  # PRD §3.1: defaults to 0


# ---------------------------------------------------------------------------
# Attribution — PRD §3.7
# ---------------------------------------------------------------------------
ATTRIBUTION_WINDOW_MIN_DAYS = 1
ATTRIBUTION_WINDOW_MAX_DAYS = 90
ATTRIBUTION_WINDOW_DEFAULT_DAYS = 7
# POSITION_BASED splits
POSITION_FIRST_FRACTION = 0.40
POSITION_LAST_FRACTION = 0.40
POSITION_MIDDLE_TOTAL_FRACTION = 0.20


# ---------------------------------------------------------------------------
# Risk score — PRD §3.10
# ---------------------------------------------------------------------------
RISK_INVALID_TRAFFIC_WEIGHT = 0.6
RISK_REJECT_RATE_WEIGHT = 0.4
RISK_MAX_SCORE = 100
RISK_CHRONIC_WINDOW_DAYS = 30  # PRD §3.10
RISK_ACUTE_WINDOW_HOURS = 24


# ---------------------------------------------------------------------------
# Test defaults — convenience values for factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ADVERTISER_LEGAL_NAME": "Acme Advertising LLC",
    "BUSINESS_LICENSE_NUMBER": "BL-12345-XYZ",
    "DAILY_BUDGET_CENTS": 100000,         # $1,000
    "LIFETIME_BUDGET_CENTS": 10_000_000,  # $100,000
    "BID_CENTS": 500,                     # $5 per click
    "FLOOR_PRICE_CENTS": 50,
    "RECHARGE_AMOUNT_CENTS": 100000,      # $1,000
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "MIN_QUALITY_SCORE",
    "MAX_QUALITY_SCORE",
    "MIN_PREDICTED_CTR",
    "MAX_PREDICTED_CTR",
    "DEFAULT_QUALITY_SCORE",
    "DEFAULT_PREDICTED_CTR",
    "SHADING_FACTOR",
    "IVT_THRESHOLD",
    "PRESCREEN_FAIL_THRESHOLD",
    "PRESCREEN_BORDERLINE_FLOOR",
    "MIN_DAILY_BUDGET_CENTS",
    "DEFAULT_LOW_BALANCE_THRESHOLD_CENTS",
    "DEFAULT_CREDIT_LINE_CENTS",
    "DEFAULT_TAX_RATE_BPS",
    "ATTRIBUTION_WINDOW_MIN_DAYS",
    "ATTRIBUTION_WINDOW_MAX_DAYS",
    "ATTRIBUTION_WINDOW_DEFAULT_DAYS",
    "POSITION_FIRST_FRACTION",
    "POSITION_LAST_FRACTION",
    "POSITION_MIDDLE_TOTAL_FRACTION",
    "RISK_INVALID_TRAFFIC_WEIGHT",
    "RISK_REJECT_RATE_WEIGHT",
    "RISK_MAX_SCORE",
    "RISK_CHRONIC_WINDOW_DAYS",
    "RISK_ACUTE_WINDOW_HOURS",
    "TEST_DEFAULTS",
]
