"""Domain thresholds — numeric constants from PRD calculations and rules.

Each constant traces to a verbatim PRD sentence.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter specifies the maximum number of items to
# return; it defaults to 10, with a minimum of 1 and a maximum of 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Voter eligibility — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "the voter must be at least 18 years of age on
# Election.election_date"
ELIGIBLE_AGE: int = 18

# PRD §3.3: "the residency duration ... must be at least 30 days"
MIN_RESIDENCY_DAYS: int = 30

# PRD §3.6: "the current server clock is within seven days of
# registration_deadline"
CURE_GRACE_DAYS: int = 7


# ---------------------------------------------------------------------------
# Recount thresholds — PRD §3.1, §3.9
# ---------------------------------------------------------------------------
# PRD §3.1: "The optional recount_threshold_pct ... when not supplied, it
# defaults to 0.005, that is, half of one percent."
DEFAULT_RECOUNT_THRESHOLD_PCT: float = 0.005

# PRD §3.9: "the recount-petition rule rejects the filing with
# ERR_RECOUNT_PETITION_INSUFFICIENT when petition_count is below 100"
MIN_PETITION_COUNT: int = 100


# ---------------------------------------------------------------------------
# Curing — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "this is gated on round_count < max_rounds (default 3,
# otherwise ERR_MAX_ROUNDS_REACHED)"
DEFAULT_MAX_ROUNDS: int = 3


# ---------------------------------------------------------------------------
# Numeric precision — PRD §2.10
# ---------------------------------------------------------------------------
# PRD §2.10: "Percentages and ratios produced by the tally pipeline ... are
# rounded to six decimal places using round-half-up."
MARGIN_DECIMAL_PLACES: int = 6

# PRD §2.10: "Voter age is computed as the integer floor of
# (Election.election_date - Voter.date_of_birth) measured in days and then
# divided by 365.25"
DAYS_PER_YEAR: float = 365.25


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "election_name": "Test General Election",
    "voter_full_name": "Test Voter",
    "precinct_code_prefix": "P",
    "default_street_pattern": ".*Main.*",
    "default_residency_address": "100 Main Street",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "ELIGIBLE_AGE",
    "MIN_RESIDENCY_DAYS",
    "CURE_GRACE_DAYS",
    "DEFAULT_RECOUNT_THRESHOLD_PCT",
    "MIN_PETITION_COUNT",
    "DEFAULT_MAX_ROUNDS",
    "MARGIN_DECIMAL_PLACES",
    "DAYS_PER_YEAR",
    "TEST_DEFAULTS",
]
