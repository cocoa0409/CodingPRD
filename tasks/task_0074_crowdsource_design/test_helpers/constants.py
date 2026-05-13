"""Domain thresholds — numeric constants drawn from PRD prose.

All constants are quoted from the PRD; tests reference them so the
boundary precision is centralized in one place.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Prize withholding (PRD §3.7)
# ---------------------------------------------------------------------------
# "the resident rate of 0.20"
RESIDENT_RATE = 0.20
# "the non-resident tier-1 rate of 0.20"
NONRES_TIER1_RATE = 0.20
# "the non-resident tier-2 rate of 0.30"
NONRES_TIER2_RATE = 0.30
# "the tier-break boundary of 400,000 cents (i.e., 4,000.00 in major units)"
TIER_BREAK_CENTS = 400_000

# ---------------------------------------------------------------------------
# Originality scoring (PRD §3.3, §3.7)
# ---------------------------------------------------------------------------
# "The preliminary-originality floor is 60.00."
PRELIM_ORIGINALITY_FLOOR = 60.00
# "peer-similarity is given a peer weight of 0.70 and public-similarity
#  is given the complementary weight of 0.30."
PEER_WEIGHT = 0.70

# ---------------------------------------------------------------------------
# Aggregation (PRD §3.5)
# ---------------------------------------------------------------------------
# "When the count of SUBMITTED scores is at least 5, the platform drops
#  the single highest and single lowest scores before computing the mean"
OUTLIER_TRIM_THRESHOLD = 5
# "30 percent of the client's aggregated_score plus 70 percent of the
#  reviewers' mean"
CLIENT_WEIGHT = 0.30

# ---------------------------------------------------------------------------
# Project timeline constraints (PRD §3.2)
# ---------------------------------------------------------------------------
# "submission_deadline must be no earlier than 72 hours after opens_at"
MIN_OPEN_TO_SUBMISSION_HOURS = 72
# "final_decision_deadline must be no earlier than 168 hours (seven full
#  days) after submission_deadline"
MIN_SUBMISSION_TO_FINAL_HOURS = 168

# ---------------------------------------------------------------------------
# Fiscal & rubric validation (PRD §3.2, §3.4)
# ---------------------------------------------------------------------------
# "a request that creates a project with prize_pool_cents below 100,000
#  cents (i.e., below 1,000.00 in major units) ... is rejected with
#  ERR_PRIZE_AMOUNT_INVALID"
MIN_PRIZE_POOL_CENTS = 100_000

# "rubric must contain between 1 and 8 criteria whose weights sum to
#  exactly 100"
RUBRIC_MIN_CRITERIA = 1
RUBRIC_MAX_CRITERIA = 8
RUBRIC_WEIGHT_SUM = 100

# ---------------------------------------------------------------------------
# Submission & reviewer caps (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
# "max_submissions_per_designer (1 to 10, default 3)"
DEFAULT_MAX_SUBMISSIONS_PER_DESIGNER = 3
# "max_concurrent_assignments (1 to 100, default 20)"
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 20

# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Helpers used by tests asserting "round half up to 2 dp" (PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up_2dp(value: float) -> float:
    """PRD §2.6: 'Whenever the system reduces a quantity to two decimal
    places, the rounding method is round half up.'"""
    quant = Decimal(str(value)).quantize(Decimal("0.01"),
                                         rounding=ROUND_HALF_UP)
    return float(quant)


def round_half_up_cents(value: float) -> int:
    """PRD §2.6: integer cents end-to-end, round_half_up."""
    return int(Decimal(str(value)).quantize(Decimal("1"),
                                            rounding=ROUND_HALF_UP))


__all__ = [
    "RESIDENT_RATE", "NONRES_TIER1_RATE", "NONRES_TIER2_RATE",
    "TIER_BREAK_CENTS",
    "PRELIM_ORIGINALITY_FLOOR", "PEER_WEIGHT",
    "OUTLIER_TRIM_THRESHOLD", "CLIENT_WEIGHT",
    "MIN_OPEN_TO_SUBMISSION_HOURS", "MIN_SUBMISSION_TO_FINAL_HOURS",
    "MIN_PRIZE_POOL_CENTS",
    "RUBRIC_MIN_CRITERIA", "RUBRIC_MAX_CRITERIA", "RUBRIC_WEIGHT_SUM",
    "DEFAULT_MAX_SUBMISSIONS_PER_DESIGNER",
    "DEFAULT_MAX_CONCURRENT_ASSIGNMENTS",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "round_half_up_2dp", "round_half_up_cents",
]
