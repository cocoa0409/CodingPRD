"""Domain thresholds and pinned numeric/temporal constants.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Answer window — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "pins Case.answer_deadline_at to exactly thirty days after
# the case's created_at timestamp".
ANSWER_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Mediation cap — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "The system also enforces a hard ceiling of three mediation
# rounds".
MEDIATION_CAP: int = 3

# PRD §3.4: "starts a session by marking it IN_PROGRESS; this is only
# permitted when now is at or after scheduled_start_at - 15 minutes".
SESSION_START_LEAD_MINUTES: int = 15

# PRD §3.4: "The session length, computed as end minus start, must be
# exactly 60, 120, or 180 minutes".
SESSION_LENGTHS_MINUTES = [60, 120, 180]


# ---------------------------------------------------------------------------
# Parenting plan overnight totals — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "Each overnight count must be in the inclusive range zero to
# 365, and the two values must sum to exactly 365".
OVERNIGHTS_TOTAL: int = 365
OVERNIGHTS_MIN: int = 0
OVERNIGHTS_MAX: int = 365


# ---------------------------------------------------------------------------
# Marriage / spousal — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "When marriage_duration_years is less than 5, attempting to
# create a SPOUSAL support order is rejected".
MIN_MARRIAGE_YEARS_FOR_SPOUSAL: int = 5

# PRD §3.5 spousal tiered transfer percentages (informational; tests
# pin actual computed values).
SPOUSAL_TIER_5_TO_10_PCT: float = 0.30
SPOUSAL_TIER_10_TO_20_PCT: float = 0.35
SPOUSAL_TIER_20_PLUS_PCT: float = 0.40
SPOUSAL_CAP_PCT_OF_HIGHER: float = 0.40


# ---------------------------------------------------------------------------
# Child support combined-income tier ceilings — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "When combined is at or below 200,000 cents (the first tier
# ceiling)".
CHILD_TIER1_CAP_CENTS: int = 200_000

# PRD §3.5: "above 200,000 but at or below 500,000 cents (the second
# tier ceiling)".
CHILD_TIER2_CAP_CENTS: int = 500_000

# PRD §3.5: "above 500,000 but at or below 1,000,000 cents (the third
# tier ceiling)".
CHILD_TIER3_CAP_CENTS: int = 1_000_000

# Child support marginal rates per tier (informational; tests pin
# computed integer values).
CHILD_TIER1_RATE: float = 0.17
CHILD_TIER2_RATE: float = 0.20
CHILD_TIER3_RATE: float = 0.22
CHILD_TIER4_RATE: float = 0.10


# ---------------------------------------------------------------------------
# Percent-of-obligor tier rates — PRD §3.5
# ---------------------------------------------------------------------------
PERCENT_OBLIGOR_TIER1_RATE: float = 0.20
PERCENT_OBLIGOR_TIER2_RATE: float = 0.22
PERCENT_OBLIGOR_TIER3_RATE: float = 0.25
PERCENT_OBLIGOR_TIER4_RATE: float = 0.27


# ---------------------------------------------------------------------------
# Jurisdiction routing — PRD §3.5 (support) and §3.6 (asset division)
# ---------------------------------------------------------------------------
# PRD §3.5: "When jurisdiction_state is CA, NY, or IL, the system uses
# the income-shares model".
INCOME_SHARES_STATES = ["CA", "NY", "IL"]

# PRD §3.5: "When jurisdiction_state is TX, FL, or WA, the system uses
# the percent-of-obligor model".
PERCENT_OBLIGOR_STATES = ["TX", "FL", "WA"]

# PRD §3.6: "When jurisdiction_state is CA, TX, or WA, the system uses
# the community-property model".
COMMUNITY_PROPERTY_STATES = ["CA", "TX", "WA"]

# PRD §3.6: "When jurisdiction_state is NY, FL, or IL, the system uses
# the equitable-distribution model".
EQUITABLE_DISTRIBUTION_STATES = ["NY", "FL", "IL"]

# PRD §3.1: "must be one of CA, NY, TX, FL, IL, or WA".
ALLOWED_JURISDICTION_STATES = ["CA", "NY", "TX", "FL", "IL", "WA"]


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "defaults to 10, has a minimum of 1, and a maximum of 100".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Allowed enum value sets (for shape assertions)
# ---------------------------------------------------------------------------
CASE_STATUSES = [
    "FILED", "AWAITING_ANSWER", "ANSWERED", "DEFAULTED",
    "DISCLOSURE", "MEDIATION", "TEMP_ORDERED",
    "AWAITING_JUDGMENT", "FINALIZED", "DISMISSED",
]

DISCLOSURE_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]

PARENTING_PLAN_STATUSES = [
    "PROPOSED", "COUNTERED", "AGREED", "CONTESTED",
    "COURT_IMPOSED", "SUPERSEDED",
]

SUPPORT_ORDER_STATUSES = ["DRAFT", "ISSUED", "SUPERSEDED", "TERMINATED"]

GUIDELINE_MODELS = ["INCOME_SHARES", "PERCENT_OBLIGOR"]

MEDIATION_SESSION_STATUSES = [
    "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW",
]

MEDIATION_OUTCOMES = ["AGREEMENT", "PARTIAL", "IMPASSE"]

TEMP_ORDER_STATUSES = ["DRAFT", "EFFECTIVE", "SUPERSEDED"]

FINAL_JUDGMENT_STATUSES = ["DRAFT", "EFFECTIVE"]

DIVISION_MODELS = ["COMMUNITY_PROPERTY", "EQUITABLE_DISTRIBUTION"]

PARTY_ROLES = ["PETITIONER", "RESPONDENT"]

SUPPORT_TYPES = ["CHILD", "SPOUSAL"]

ORDER_KINDS = ["TEMPORARY", "FINAL"]

LEGAL_CUSTODY_VALUES = ["JOINT", "PETITIONER_SOLE", "RESPONDENT_SOLE"]

PHYSICAL_CUSTODY_VALUES = ["JOINT", "PETITIONER_PRIMARY", "RESPONDENT_PRIMARY"]


# ---------------------------------------------------------------------------
# Test default inputs (a stable seed for tests that don't care about the
# precise numbers).
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # Default disclosure inputs (in cents).
    "P_GROSS_CENTS": 300_000,
    "R_GROSS_CENTS": 600_000,
    "P_TAXES_CENTS": 0,
    "R_TAXES_CENTS": 0,
    "P_HEALTH_CENTS": 0,
    "R_HEALTH_CENTS": 0,
    "P_CHILDCARE_CENTS": 0,
    "R_CHILDCARE_CENTS": 0,
    "P_ASSETS_CENTS": 1_000_000,
    "R_ASSETS_CENTS": 2_000_000,
    "P_DEBTS_CENTS": 0,
    "R_DEBTS_CENTS": 0,
    # Default parenting plan overnights.
    "P_OVERNIGHTS": 100,
    "R_OVERNIGHTS": 265,
    # Default marriage interval (>= 5 years for spousal eligibility).
    "DEFAULT_MARRIAGE_DATE": "2010-01-01",
    "DEFAULT_SEPARATION_DATE": "2025-01-01",
}


__all__ = [
    "ANSWER_WINDOW_DAYS",
    "MEDIATION_CAP",
    "SESSION_START_LEAD_MINUTES",
    "SESSION_LENGTHS_MINUTES",
    "OVERNIGHTS_TOTAL",
    "OVERNIGHTS_MIN",
    "OVERNIGHTS_MAX",
    "MIN_MARRIAGE_YEARS_FOR_SPOUSAL",
    "SPOUSAL_TIER_5_TO_10_PCT",
    "SPOUSAL_TIER_10_TO_20_PCT",
    "SPOUSAL_TIER_20_PLUS_PCT",
    "SPOUSAL_CAP_PCT_OF_HIGHER",
    "CHILD_TIER1_CAP_CENTS",
    "CHILD_TIER2_CAP_CENTS",
    "CHILD_TIER3_CAP_CENTS",
    "CHILD_TIER1_RATE",
    "CHILD_TIER2_RATE",
    "CHILD_TIER3_RATE",
    "CHILD_TIER4_RATE",
    "PERCENT_OBLIGOR_TIER1_RATE",
    "PERCENT_OBLIGOR_TIER2_RATE",
    "PERCENT_OBLIGOR_TIER3_RATE",
    "PERCENT_OBLIGOR_TIER4_RATE",
    "INCOME_SHARES_STATES",
    "PERCENT_OBLIGOR_STATES",
    "COMMUNITY_PROPERTY_STATES",
    "EQUITABLE_DISTRIBUTION_STATES",
    "ALLOWED_JURISDICTION_STATES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "CASE_STATUSES",
    "DISCLOSURE_STATUSES",
    "PARENTING_PLAN_STATUSES",
    "SUPPORT_ORDER_STATUSES",
    "GUIDELINE_MODELS",
    "MEDIATION_SESSION_STATUSES",
    "MEDIATION_OUTCOMES",
    "TEMP_ORDER_STATUSES",
    "FINAL_JUDGMENT_STATUSES",
    "DIVISION_MODELS",
    "PARTY_ROLES",
    "SUPPORT_TYPES",
    "ORDER_KINDS",
    "LEGAL_CUSTODY_VALUES",
    "PHYSICAL_CUSTODY_VALUES",
    "TEST_DEFAULTS",
]
