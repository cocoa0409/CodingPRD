"""Domain thresholds and defaults.

Numeric constants used by tests; sourced from PRD §3 prose. NON_EXISTENT_UUID
is supplied by the framework.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# League creation default ranges (PRD §3.1)
# ---------------------------------------------------------------------------
NAME_MIN_LEN = 1
NAME_MAX_LEN = 80
TEAM_NAME_MIN_LEN = 1
TEAM_NAME_MAX_LEN = 60

SEASON_YEAR_MIN = 2020

TEAM_COUNT_MIN = 4
TEAM_COUNT_MAX = 16

ROSTER_SIZE_MIN = 12
ROSTER_SIZE_MAX = 20

STARTER_COUNT_MIN = 7
STARTER_COUNT_MAX = 11

IR_SLOTS_MIN = 0
IR_SLOTS_MAX = 4

FAAB_BUDGET_MIN = 0
FAAB_BUDGET_MAX = 1000

AUCTION_BUDGET_MIN = 0
AUCTION_BUDGET_MAX = 500
AUCTION_BUDGET_DEFAULT = 200

KEEPER_CAP_DEFAULT = 0

VETO_QUORUM_PCT_MIN = 25
VETO_QUORUM_PCT_MAX = 100
VETO_QUORUM_PCT_DEFAULT = 50

TRADE_REVIEW_HOURS_MIN = 0
TRADE_REVIEW_HOURS_MAX = 168
TRADE_REVIEW_HOURS_DEFAULT = 48

WAIVER_PERIOD_HOURS_MIN = 0
WAIVER_PERIOD_HOURS_MAX = 168
WAIVER_PERIOD_HOURS_DEFAULT = 48

PLAYOFF_TEAM_COUNTS_ALLOWED = (2, 4, 8)

REGULAR_SEASON_WEEKS_MIN = 10
REGULAR_SEASON_WEEKS_MAX = 14


# ---------------------------------------------------------------------------
# Scoring constants (PRD §3.5)
# ---------------------------------------------------------------------------
RECEPTION_HALF_PPR = 0.5
RECEPTION_PPR = 1.0
SCORING_DECIMAL_PLACES = 2


# ---------------------------------------------------------------------------
# Keeper economy (PRD §3.2)
# ---------------------------------------------------------------------------
AUCTION_INFLATION_RATE = 1.10
AUCTION_KEEPER_FLOOR_DOLLARS = 1
SNAKE_UNDRAFTED_LATE_OFFSET = 5  # regular_season_weeks + 5


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Test defaults for fixture-built leagues. Chosen to satisfy every
# range constraint in PRD §3.1 without sitting at any boundary.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "SEASON_YEAR": 2026,
    "FAAB_BUDGET": 100,
    "AUCTION_BUDGET": 200,
    "WAIVER_PERIOD_HOURS": 48,
    "TRADE_REVIEW_HOURS": 48,
    "VETO_QUORUM_PCT": 50,
    "REGULAR_SEASON_WEEKS": 10,
    "PLAYOFF_TEAM_COUNT": 2,
}


__all__ = [
    "NAME_MIN_LEN",
    "NAME_MAX_LEN",
    "TEAM_NAME_MIN_LEN",
    "TEAM_NAME_MAX_LEN",
    "SEASON_YEAR_MIN",
    "TEAM_COUNT_MIN",
    "TEAM_COUNT_MAX",
    "ROSTER_SIZE_MIN",
    "ROSTER_SIZE_MAX",
    "STARTER_COUNT_MIN",
    "STARTER_COUNT_MAX",
    "IR_SLOTS_MIN",
    "IR_SLOTS_MAX",
    "FAAB_BUDGET_MIN",
    "FAAB_BUDGET_MAX",
    "AUCTION_BUDGET_MIN",
    "AUCTION_BUDGET_MAX",
    "AUCTION_BUDGET_DEFAULT",
    "KEEPER_CAP_DEFAULT",
    "VETO_QUORUM_PCT_MIN",
    "VETO_QUORUM_PCT_MAX",
    "VETO_QUORUM_PCT_DEFAULT",
    "TRADE_REVIEW_HOURS_MIN",
    "TRADE_REVIEW_HOURS_MAX",
    "TRADE_REVIEW_HOURS_DEFAULT",
    "WAIVER_PERIOD_HOURS_MIN",
    "WAIVER_PERIOD_HOURS_MAX",
    "WAIVER_PERIOD_HOURS_DEFAULT",
    "PLAYOFF_TEAM_COUNTS_ALLOWED",
    "REGULAR_SEASON_WEEKS_MIN",
    "REGULAR_SEASON_WEEKS_MAX",
    "RECEPTION_HALF_PPR",
    "RECEPTION_PPR",
    "SCORING_DECIMAL_PLACES",
    "AUCTION_INFLATION_RATE",
    "AUCTION_KEEPER_FLOOR_DOLLARS",
    "SNAKE_UNDRAFTED_LATE_OFFSET",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "TEST_DEFAULTS",
]
