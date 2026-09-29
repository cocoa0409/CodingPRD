"""Shared literals used across the suite.

The governance-policy knob values below are stated explicitly on every adopt
call so that no expected value in the suite depends on a fallback the PRD does
not publish.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
# The clock reads exactly this instant until a client moves it.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Cycle years used by the suite
# ---------------------------------------------------------------------------
CYCLE_YEAR = 2026
NEXT_CYCLE_YEAR = 2027

POLICY_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
POLICY_EFFECTIVE_FROM_LATER = "2026-03-01T00:00:00Z"
NEXT_POLICY_EFFECTIVE_FROM = "2027-01-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Governance-policy knob values (every field is supplied explicitly)
# ---------------------------------------------------------------------------
POLICY_KNOBS = {
    "authorized_seats": 9,
    "independence_min_pct": 66.67,
    "independence_standard": "BRIGHT_LINE",
    "bright_line_payment_floor_cents": 100000000,
    "bright_line_revenue_pct": 2.0,
    "bright_line_lookback_years": 3,
    "enhanced_lookback_years": 5,
    "enhanced_charitable_pct": 2.0,
    "max_public_boards_default": 4,
    "max_public_boards_sitting_ceo": 2,
    "interlock_max_shared_boards": 2,
    "mandatory_retirement_age": 75,
    "max_tenure_years": 15,
    "min_completed_interviews": 3,
    "quorum_size": 3,
    "approval_threshold_pct": 66.67,
    "annual_cash_retainer_cents": 12000000,
    "committee_member_fee_cents": 1500000,
    "committee_chair_premium_cents": 2500000,
    "equity_grant_value_cents": 20000000,
    "ownership_multiple": 5.0,
    "ownership_grace_years": 5,
    "education_hours_required": 8.0,
    "readiness_min_score": 60.0,
}

# Individual knob values worth naming where an assertion depends on them.
AUTHORIZED_SEATS = 9
INDEPENDENCE_MIN_PCT = 66.67
BRIGHT_LINE_PAYMENT_FLOOR_CENTS = 100000000
BRIGHT_LINE_REVENUE_PCT = 2.0
BRIGHT_LINE_LOOKBACK_YEARS = 3
ENHANCED_LOOKBACK_YEARS = 5
ENHANCED_CHARITABLE_PCT = 2.0
MAX_PUBLIC_BOARDS_DEFAULT = 4
MAX_PUBLIC_BOARDS_SITTING_CEO = 2
INTERLOCK_MAX_SHARED_BOARDS = 2
MANDATORY_RETIREMENT_AGE = 75
MAX_TENURE_YEARS = 15
MIN_COMPLETED_INTERVIEWS = 3
QUORUM_SIZE = 3
APPROVAL_THRESHOLD_PCT = 66.67
ANNUAL_CASH_RETAINER_CENTS = 12000000
COMMITTEE_MEMBER_FEE_CENTS = 1500000
COMMITTEE_CHAIR_PREMIUM_CENTS = 2500000
EQUITY_GRANT_VALUE_CENTS = 20000000
OWNERSHIP_MULTIPLE = 5.0
OWNERSHIP_GRACE_YEARS = 5
EDUCATION_HOURS_REQUIRED = 8.0
READINESS_MIN_SCORE = 60.0

# ---------------------------------------------------------------------------
# Committee defaults (PRD 3.8)
# ---------------------------------------------------------------------------
COMMITTEE_MIN_SEATS_DEFAULT = 3

# ---------------------------------------------------------------------------
# Slate budget default (PRD 3.6)
# ---------------------------------------------------------------------------
SEARCH_FEE_BUDGET_DEFAULT_CENTS = 10000000000

# ---------------------------------------------------------------------------
# Readiness-score components (PRD 3.4)
# ---------------------------------------------------------------------------
READINESS_INTERVIEW_MULTIPLIER = 8.0
READINESS_INTERVIEW_CAP = 40.0
READINESS_INDEPENDENCE_POINTS = 30.0
READINESS_CHANNEL_POINTS = {
    "SEARCH_FIRM": 20.0,
    "NETWORK_REFERRAL": 15.0,
    "SHAREHOLDER_PROPOSAL": 10.0,
    "UNIVERSAL_PROXY_NOMINATION": 5.0,
}
READINESS_BOARD_BASE_POINTS = 10.0
READINESS_BOARD_PENALTY_PER_BOARD = 2.5
READINESS_MAX_SCORE = 100.0
READINESS_ADVERSE_REFERENCE_PENALTY = 15.0

# ---------------------------------------------------------------------------
# Skills gap analysis (PRD 3.1)
# ---------------------------------------------------------------------------
GAP_COVERAGE_MIN_RATING = 3
GAP_RISK_OVERSIGHT_MULTIPLIER = 1.5
CRITICALITY_RANK = {"CORE": 0, "STRATEGIC": 1, "EMERGING": 2}

# ---------------------------------------------------------------------------
# Compensation award offset tiers (PRD 3.9)
# ---------------------------------------------------------------------------
OFFSET_TIER_LOWER_BOUND_CENTS = 30000000
OFFSET_TIER_UPPER_BOUND_CENTS = 40000000
OFFSET_PCT_NONE = 0.0
OFFSET_PCT_MID = 2.5
OFFSET_PCT_HIGH = 5.0

# ---------------------------------------------------------------------------
# Election cascade (PRD 3.7)
# ---------------------------------------------------------------------------
SEEDED_ONBOARDING_MODULE_CODES = ["BOARD_ORIENTATION", "COMMITTEE_ONBOARD", "DOC_PORTAL"]
SEEDED_ONBOARDING_DUE_DAYS = 90
SEEDED_ONBOARDING_DUE_ON = "2026-10-30"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
