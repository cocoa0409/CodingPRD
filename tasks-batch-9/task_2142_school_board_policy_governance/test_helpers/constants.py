"""Domain thresholds and shared literals drawn from the requirements narrative."""

# The logical clock starts here on server start.
CLOCK_START = "2026-08-01T00:00:00Z"

# Public-comment minute budgets fixed at meeting creation from meeting_type.
PUBLIC_COMMENT_BUDGET = {
    "REGULAR": 30,
    "SPECIAL": 5,
    "EMERGENCY": 0,
}

# Per-speaker ceiling / floor, the crowd threshold and the per-item card cap.
MAX_MINUTES_PER_SPEAKER = 3
MIN_MINUTES_PER_SPEAKER = 1
EQUAL_SPLIT_THRESHOLD = 4
MAX_SPEAKERS_PER_ITEM = 5

# Statutory notice lead times, in hours, by meeting_type.
NOTICE_LEAD_HOURS = {
    "REGULAR": 72,
    "SPECIAL": 48,
    "EMERGENCY": 24,
}

# Symmetric calendar buffer around a meeting instant, in minutes.
MEETING_SEPARATION_MINUTES = 240

# Waiver duration caps, in whole days, by the policy's legal_requirement_level.
WAIVER_MAX_DAYS = {
    "REQUIRED_BY_LAW": 90,
    "RECOMMENDED": 180,
    "LOCAL_DISCRETION": 365,
}

# The three-year policy review cycle.
REVIEW_CYCLE_DAYS = 1095

# Delay between adoption and effect for a regularly adopted policy.
REGULAR_EFFECTIVE_DELAY_DAYS = 30

# Superintendent score bounds.
SCORE_MIN = 1.00
SCORE_MAX = 5.00

# Pagination window.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Long-lived term used for trustees that must outlive every scenario.
LONG_TERM_START = "2026-01-01T00:00:00Z"
LONG_TERM_END = "2030-12-31T00:00:00Z"

TRUSTEE_ROSTER = [
    ("Ada Reyes", "Reyes Dental"),
    ("Ben Cole", "Cole Freight"),
    ("Cara Lin", "Lin Architects"),
    ("Dev Rao", "Rao Legal"),
    ("Eli Shaw", "Shaw Farms"),
    ("Fern Ott", "Ott Bakery"),
    ("Gus Pike", "Pike Marine"),
]
