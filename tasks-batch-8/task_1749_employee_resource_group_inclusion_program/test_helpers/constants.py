"""Domain thresholds and named instants from the PRD's calculation rules."""

# Logical clock
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
TENURE_SAFE_CLOCK = "2026-11-01T00:00:00Z"  # 92 days after the default clock
STANDARD_TERM_ENDS_AT = "2027-02-01T00:00:00Z"

# Charter / membership
FOUNDING_MEMBER_MINIMUM = 10

# Leadership terms
LEADER_TENURE_DAYS = 90
TERM_LIMIT_PER_EMPLOYEE_PER_GROUP = 2

# Climate
CLIMATE_THRESHOLD = 3.00

# Mentoring
MENTORING_BUFFER_DAYS = 14

# Allocation waterfall category weights (tenths)
CATEGORY_WEIGHT_TENTHS = {
    "AFFINITY": 10,
    "PROFESSIONAL": 12,
    "COMMUNITY_OUTREACH": 15,
}

# Event impact points
BASE_POINTS = {
    "WORKSHOP": 20,
    "SOCIAL": 10,
    "RECRUITING": 80,
    "COMMUNITY": 40,
}
SPONSOR_BONUS = 10
POINTS_CAP = 100
LOW_ATTENDANCE_THRESHOLD_PCT = 25.00
TIER_MID_FLOOR_PCT = 25.00
TIER_HIGH_FLOOR_PCT = 75.00

# Matching top-up
SCOUT_RATE = 0.10
TIER1_CAP_CENTS = 1_000_000
HIGH_MATCH_RATE = 0.20
LOW_MATCH_RATE = 0.05

# Common test event window (strictly after the default logical clock)
DEFAULT_EVENT_STARTS_AT = "2026-08-10T10:00:00Z"
DEFAULT_EVENT_ENDS_AT = "2026-08-10T12:00:00Z"

# Ten founding members used by most charter flows (emp_f01 doubles as the
# usual post-activation term leader).
DEFAULT_MEMBER_IDS = [f"emp_f{i:02d}" for i in range(1, 11)]
