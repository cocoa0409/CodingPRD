"""Domain thresholds — numeric constants from PRD calculations.

Every constant below is taken verbatim from a §3 narrative or §2.x
convention in the PRD. Tests use these by symbolic name so the boundary
intent is visible.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# FAA duty / rest limits — PRD §3.5.
# ---------------------------------------------------------------------------
# "the gap from the candidate's last_duty_end_at to the candidate pairing's
#  earliest report_at must be at least 600 minutes (the ten-hour crew-rest
#  minimum)"
CREW_REST_MIN_MINUTES = 600          # 10 hours

# "the candidate's cumulative_duty_minutes_7d plus the candidate pairing's
#  total_duty_minutes must be at most 3600 minutes (the rolling 60-hour,
#  seven-day duty cap)"
MAX_DUTY_MINUTES_7D = 3600           # 60 hours

# "the candidate's cumulative_block_minutes_30d plus the pairing's
#  total_block_minutes must be at most 6000 minutes (the rolling 100-hour,
#  thirty-day block cap)"
MAX_BLOCK_MINUTES_30D = 6000         # 100 hours

# "every DutyPeriod belonging to the candidate pairing must have a
#  duty_minutes of at most 840 minutes (the 14-hour single-duty-period cap)"
MAX_DUTY_MINUTES_SINGLE = 840        # 14 hours


# ---------------------------------------------------------------------------
# Pay credit calculation — PRD §3.6.
# ---------------------------------------------------------------------------
# "multiplying the integer deadhead-minute total by the deadhead pay ratio
#  of one half and then taking the floor of the product"
DEADHEAD_PAY_RATIO = 0.5

# "pay_credit_minutes is the greater of the raw credit and the
#  minimum-pay-credit floor of 240 minutes (four hours)"
MIN_PAY_CREDIT_FLOOR_MINUTES = 240   # 4-hour minimum credit per pairing


# ---------------------------------------------------------------------------
# Trade lifecycle — PRD §3.8.
# ---------------------------------------------------------------------------
# "allowed only while revision_count is strictly less than 3"
TRADE_MAX_REVISIONS = 3

# "After 24 hours of no movement from the trade's created_at, a clock advance
#  moves a PROPOSED or COUNTER_PROPOSED trade to EXPIRED."
TRADE_EXPIRY_HOURS = 24


# ---------------------------------------------------------------------------
# Bid window — PRD §3.2.
# ---------------------------------------------------------------------------
# "the inclusive 24-hour cutoff is enforced strictly: a start_at minus 24
#  hours that exactly equals now is still permitted; anything later is
#  rejected"
BID_CUTOFF_HOURS_BEFORE_START = 24


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Convenience defaults for factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "BASE_AIRPORT_DEFAULT": "DFW",
    "BASE_AIRPORT_ALT": "JFK",
    "DEFAULT_BID_WINDOW_ID": "BW-2026-Q2",
}


__all__ = [
    "BID_CUTOFF_HOURS_BEFORE_START",
    "CREW_REST_MIN_MINUTES",
    "DEADHEAD_PAY_RATIO",
    "MAX_BLOCK_MINUTES_30D",
    "MAX_DUTY_MINUTES_7D",
    "MAX_DUTY_MINUTES_SINGLE",
    "MIN_PAY_CREDIT_FLOOR_MINUTES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
    "TRADE_EXPIRY_HOURS",
    "TRADE_MAX_REVISIONS",
]
