"""Domain thresholds and numeric constants stated by the PRD.

Every value here is quoted from PRD prose (§2.3, §2.5, §2.7, §2.11, §3.x). Generic
helpers such as NON_EXISTENT_UUID come from the framework, not from this file.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Request-shape ranges (PRD §2.5 rung 4)
# ---------------------------------------------------------------------------
CYCLE_YEAR_MIN = 2020
CYCLE_YEAR_MAX = 2050
VOTING_SEAT_COUNT_MIN = 3
VOTING_SEAT_COUNT_MAX = 12
MEASURE_LIFE_YEARS_MIN = 1
MEASURE_LIFE_YEARS_MAX = 40
SEAT_CAPACITY_MIN = 1
OFFICIAL_HEADCOUNT_MIN = 1

# ---------------------------------------------------------------------------
# Committee seating and quorum (PRD §3.1)
# ---------------------------------------------------------------------------
QUORUM_FRACTION_NUMERATOR = 2
QUORUM_FRACTION_DENOMINATOR = 3
SEATING_FRACTION_NUMERATOR = 2
SEATING_FRACTION_DENOMINATOR = 3
REQUIRED_CHAIR_COUNT = 1

# ---------------------------------------------------------------------------
# Impact analysis / benefit-cost (PRD §2.7, §3.3)
# ---------------------------------------------------------------------------
OCCUPANCY_SHARES = {"R3": 0.62, "R2": 0.18, "B": 0.12, "A2": 0.08}
OCCUPANCY_KEYS = ("R3", "R2", "B", "A2")
PRELIMINARY_HORIZON_YEARS = 15
DISCOUNT_RATE = 0.03
ANNUITY_FACTOR_DECIMALS = 6
BENEFIT_COST_RATIO_DECIMALS = 2
BENEFIT_COST_RATIO_FLOOR = 1.00

# ---------------------------------------------------------------------------
# Comment window (PRD §2.11, §3.4)
# ---------------------------------------------------------------------------
MINIMUM_COMMENT_PERIOD_DAYS = 30
COMMENT_EXTENSION_DAYS = 30
MAX_COMMENT_EXTENSIONS = 2

# ---------------------------------------------------------------------------
# Docket score (PRD §3.4)
# ---------------------------------------------------------------------------
DOCKET_WEIGHT_STRINGENCY = 0.45
DOCKET_WEIGHT_SUPPORT = 0.35
DOCKET_WEIGHT_COST = 0.20
STRINGENCY_AWARD = {
    "MORE_STRINGENT": 1.00,
    "NEUTRAL": 0.60,
    "CLARIFYING": 0.40,
    "LESS_STRINGENT": 0.20,
}
COST_POINTS_CAP_CENTS = 200_000_000
NEUTRAL_SUPPORT_RATIO = 0.5000
SUPPORT_RATIO_DECIMALS = 4
COST_POINTS_DECIMALS = 6
DOCKET_SCORE_DECIMALS = 2
RANK_ONE_BONUS = 5.00
RANK_TWO_BONUS = 2.00
RANK_OTHER_BONUS = 0.00

# ---------------------------------------------------------------------------
# Hearings (PRD §2.11, §3.5)
# ---------------------------------------------------------------------------
HEARING_NOTICE_DAYS = 14
HEARING_BUFFER_MINUTES = 60
AGENDA_MAX_ITEMS = 8
SUPERMAJORITY_FRACTION = 0.60
STRINGENCY_FLOOR_SECTION_PREFIXES = ("9", "10")

# ---------------------------------------------------------------------------
# Adoption rule schedule (PRD §3.7)
# ---------------------------------------------------------------------------
BACKLOG_ANNUALIZATION_NUMERATOR = 60
BACKLOG_ANNUALIZATION_DENOMINATOR = 365
GRACE_TIER_SMALL_THRESHOLD = 500
GRACE_TIER_MEDIUM_THRESHOLD = 5000
GRACE_DAYS_SMALL = 90
GRACE_DAYS_MEDIUM = 180
GRACE_DAYS_LARGE = 365
MINIMUM_NOTICE_DAYS = 120
PRIOR_CODE_EXPIRY_EXTRA_DAYS = 365

# ---------------------------------------------------------------------------
# Local amendments and interpretations (PRD §2.11, §3.8)
# ---------------------------------------------------------------------------
LOCAL_FILING_WINDOW_DAYS = 90
MAX_LOCAL_REVISION_ROUNDS = 2
APPEAL_WINDOW_DAYS = 30
MAX_APPEAL_ROUNDS = 2

# ---------------------------------------------------------------------------
# Training and readiness (PRD §3.7, §3.9)
# ---------------------------------------------------------------------------
TRAINING_READINESS_THRESHOLD_PCT = 80.00
STATEWIDE_READINESS_THRESHOLD_PCT = 80.00
COMPLIANCE_PCT_CAP = 100.00
COMPLIANCE_PCT_DECIMALS = 2

# ---------------------------------------------------------------------------
# Convenience payload defaults reused by tests
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "CYCLE_YEAR": 2027,
    "MODEL_CODE_EDITION": "IBC-2027",
    "INTAKE_OPENS_AT": "2026-08-01T00:00:00Z",
    "INTAKE_CLOSES_AT": "2026-10-01T00:00:00Z",
    "VOTING_SEAT_COUNT": 6,
    "SEAT_CAPACITY": 60,
}
