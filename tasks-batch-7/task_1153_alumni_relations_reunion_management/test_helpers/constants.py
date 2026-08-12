"""Domain thresholds and numeric constants named in the PRD."""

# Logical clock (PRD §2.4): startup default reading before any clock operation.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Research cases (PRD §3.2)
LEAD_CONFIDENCE_MIN = 60          # verify demands lead_confidence of at least 60
CASE_REOPEN_LIMIT = 3             # reopening capped once reopened_count reaches 3

# Ticket pricing pipeline (PRD §3.4)
COMMITTEE_DISCOUNT_FACTOR = 0.75  # committee members: price scaled by 0.75
LATE_FEE_CENTS = 1500             # flat $15.00 late fee
LATE_FEE_WINDOW_DAYS = 7          # applies once clock is later than event_date - 7 days
EARLY_BIRD_CUTOFF_DAYS = 60       # cutoff is sixty days before event_date

# Engagement scoring (PRD §3.7)
EVENT_WEIGHT = 0.50
GIVING_WEIGHT = 0.30
SERVICE_WEIGHT = 0.20
EVENT_POINTS_PER_REGISTRATION = 25
SERVICE_POINTS_PER_MEMBERSHIP = 20
GIVING_POINT_PER_DOLLARS = 10     # one point per ten dollars of fulfilled giving
POINTS_CAP = 100
SCORE_CAP = 100.00
TIER_HIGH_THRESHOLD = 70.00       # inclusive
TIER_MEDIUM_THRESHOLD = 30.00     # inclusive

# Giving propensity (PRD §3.7)
PROPENSITY_SCORE_WEIGHT = 0.7
PROPENSITY_RECENCY_BONUS = 0.15
PROPENSITY_RECENCY_WINDOW_DAYS = 365
PROPENSITY_CAPACITY_CAP = 0.25
PROPENSITY_CAP = 1.00

# Pledges (PRD §3.6)
PLEDGE_MIN_AMOUNT_CENTS = 100
MATCHING_BPS_DENOMINATOR = 10000  # 10000 bps == 1.0x match

# Chapter programs (PRD §3.5)
VENUE_BUFFER_MINUTES = 60         # each program occupies [start, end + 60min]

# Pagination (PRD §2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
