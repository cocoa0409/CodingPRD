"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Monetary constants
# ---------------------------------------------------------------------------
# PRD §3.5: "the federal K-12 annual cap of $10,000 (1,000,000 cents)".
K12_ANNUAL_CAP_CENTS: int = 1_000_000

# PRD §3.3: "the annual gift exclusion of $18,000, equivalently 1,800,000
# cents".
ANNUAL_GIFT_EXCLUSION_CENTS: int = 1_800_000

# PRD §3.5: "the penalty rate of 10% (0.10)".
PENALTY_RATE: float = 0.10


# ---------------------------------------------------------------------------
# Cadence values — PRD §3.3 RecurringPlan.cadence_days valid values
# ---------------------------------------------------------------------------
CADENCE_WEEKLY_DAYS: int = 7
CADENCE_BIWEEKLY_DAYS: int = 14
CADENCE_MONTHLY_DAYS: int = 30
CADENCE_QUARTERLY_DAYS: int = 90
CADENCE_ANNUAL_DAYS: int = 365
VALID_CADENCE_DAYS = (
    CADENCE_WEEKLY_DAYS,
    CADENCE_BIWEEKLY_DAYS,
    CADENCE_MONTHLY_DAYS,
    CADENCE_QUARTERLY_DAYS,
    CADENCE_ANNUAL_DAYS,
)

SECONDS_PER_DAY: int = 86_400


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# IRS permissible-family set for beneficiary-change approval — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "the proposed beneficiary's relationship_family_code must be one
# of CHILD, SIBLING, NIECE_NEPHEW, COUSIN, FIRST_COUSIN_ONCE_REMOVED, SPOUSE,
# IN_LAW, or PARENT — SELF is not in the permissible set for a change".
PERMISSIBLE_RELATIONSHIPS = frozenset({
    "CHILD",
    "SIBLING",
    "NIECE_NEPHEW",
    "COUSIN",
    "FIRST_COUSIN_ONCE_REMOVED",
    "SPOUSE",
    "IN_LAW",
    "PARENT",
})

# PRD §3.6 generation-skip example: "the canonical example being a change
# from a CHILD beneficiary to a PARENT or IN_LAW beneficiary".
GENERATION_SKIP_UPWARD_RELATIONSHIPS = frozenset({"PARENT", "IN_LAW"})


# ---------------------------------------------------------------------------
# Test defaults — used when a test does not pin a specific value
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # A generous deduction cap so most tests do not trip the cap.
    "DEDUCTION_CAP_CENTS": 500_000,
    # A generous lifetime cap so most tests do not trip the lifetime cap.
    "LIFETIME_AGGREGATE_CAP_CENTS": 500_000_000,
    # A modest contribution amount well below the gift exclusion
    # (1,800,000 cents) so tests can settle multiple contributions per
    # donor per year without tripping the exclusion.
    "DEFAULT_CONTRIBUTION_CENTS": 100_000,
    "DEFAULT_BENEFICIARY_DOB": "2010-06-15",
}


__all__ = [
    "K12_ANNUAL_CAP_CENTS",
    "ANNUAL_GIFT_EXCLUSION_CENTS",
    "PENALTY_RATE",
    "CADENCE_WEEKLY_DAYS",
    "CADENCE_BIWEEKLY_DAYS",
    "CADENCE_MONTHLY_DAYS",
    "CADENCE_QUARTERLY_DAYS",
    "CADENCE_ANNUAL_DAYS",
    "VALID_CADENCE_DAYS",
    "SECONDS_PER_DAY",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "PERMISSIBLE_RELATIONSHIPS",
    "GENERATION_SKIP_UPWARD_RELATIONSHIPS",
    "TEST_DEFAULTS",
]
