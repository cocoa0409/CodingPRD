"""Domain thresholds and weights — numeric constants from PRD §2 and §3.

These are the rule-bearing magic numbers the implementation is required to
honour. Tests cite the same numbers via these names so a single change in
PRD propagates cleanly.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Listing fiscal bounds — PRD §3.2.
# ---------------------------------------------------------------------------
MIN_LIST_PRICE_CENTS: int = 1_000_000   # >= $10,000
MAX_CO_OP_PCT: float = 0.06              # inclusive upper bound
MAX_TOTAL_COMMISSION_PCT: float = 0.10   # inclusive upper bound

# Agent split — PRD §3.1.
AGENT_SPLIT_MIN_EXCLUSIVE: float = 0.0
AGENT_SPLIT_MAX_INCLUSIVE: float = 1.0
AGENT_SPLIT_DEFAULT: float = 0.70

# Bedroom / bathroom — PRD §3.2 / §3.3.
BEDROOMS_MIN: int = 0
BEDROOMS_MAX: int = 20
BATHROOMS_MIN: float = 0.0
BATHROOMS_MAX: float = 20.0
BATHROOMS_STEP: float = 0.5

# ZIP code — PRD §3.2.
ZIP_CODE_LENGTH: int = 5


# ---------------------------------------------------------------------------
# Showing window — PRD §3.5.
# ---------------------------------------------------------------------------
SHOWING_MIN_DURATION_MINUTES: int = 15
SHOWING_MAX_DURATION_HOURS: int = 4
SHOWING_MAX_DURATION_MINUTES: int = SHOWING_MAX_DURATION_HOURS * 60


# ---------------------------------------------------------------------------
# Listing lifetime — PRD §3.2.
# ---------------------------------------------------------------------------
LISTING_LIFETIME_DAYS: int = 180


# ---------------------------------------------------------------------------
# Buyer-match scoring — PRD §3.4.
# ---------------------------------------------------------------------------
W_PRICE: float = 0.40
W_LOC: float = 0.25
W_BB: float = 0.20
W_FEAT: float = 0.15

# Cutoff: candidates whose score is strictly less than 50 are excluded.
# Candidates whose score is exactly 50.00 are INCLUDED (>= comparison).
SCORE_CUTOFF: float = 50.0


# ---------------------------------------------------------------------------
# Lockbox — PRD §2.8.
# ---------------------------------------------------------------------------
ACCESS_CODE_LENGTH: int = 6


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Bundle for tests that want to introspect.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "LIST_PRICE_CENTS": 50_000_000,         # $500,000
    "CO_OP_PCT": 0.025,
    "TOTAL_COMMISSION_PCT": 0.06,
    "BROKERAGE_SPLIT_PCT": 0.70,
    "OFFER_PRICE_CENTS": 50_000_000,
    "EARNEST_MONEY_CENTS": 1_000_000,
    "BEDROOMS": 3,
    "BATHROOMS": 2.0,
    "ZIP_CODE": "94110",
}


__all__ = [
    "MIN_LIST_PRICE_CENTS",
    "MAX_CO_OP_PCT",
    "MAX_TOTAL_COMMISSION_PCT",
    "AGENT_SPLIT_MIN_EXCLUSIVE",
    "AGENT_SPLIT_MAX_INCLUSIVE",
    "AGENT_SPLIT_DEFAULT",
    "BEDROOMS_MIN",
    "BEDROOMS_MAX",
    "BATHROOMS_MIN",
    "BATHROOMS_MAX",
    "BATHROOMS_STEP",
    "ZIP_CODE_LENGTH",
    "SHOWING_MIN_DURATION_MINUTES",
    "SHOWING_MAX_DURATION_HOURS",
    "SHOWING_MAX_DURATION_MINUTES",
    "LISTING_LIFETIME_DAYS",
    "W_PRICE",
    "W_LOC",
    "W_BB",
    "W_FEAT",
    "SCORE_CUTOFF",
    "ACCESS_CODE_LENGTH",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
