"""Domain thresholds and shared scenario constants from the PRD."""

# Logical clock (PRD §2.5): startup default before any set call.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Statutory / business windows (PRD §2.5, §3.2, §3.3, §3.4, §3.5, §3.7)
CURE_PERIOD_DAYS = 14                 # cure_deadline = notice sent_at + 14 days
REDEMPTION_PERIOD_DAYS = 10           # redemption_deadline = first quote issued_at + 10 days
ACCEPT_WINDOW_HOURS = 48              # unacknowledged ASSIGNED assignment expires after 48h
PROPERTY_RETENTION_DAYS = 15          # disposal allowed once >= collateral_secured_at + 15d
DEFICIENCY_NOTICE_DAYS = 30           # send window: now <= sold_at + 30 days
ROLLING_WINDOW_DAYS = 90              # rolling performance score window

# Agent performance scoring (PRD §3.3)
SCORE_BASE = 100
BREACH_PENALTY = 25
EXPIRED_PENALTY = 10
FAST_SECURE_BONUS = 2
FAST_SECURE_DAYS = 14
SUSPENSION_THRESHOLD = 40

# Pricing / estimate constants (PRD §3.6, §3.7)
RESERVE_FLOOR_RATIO = 0.5
RELIST_MARKDOWN = 0.95
EST_RECOVERY_RATIO = 0.9
DAYS_PER_YEAR = 365
GRADE_MULTIPLIERS = {
    "EXCELLENT": 0.85,
    "GOOD": 0.75,
    "FAIR": 0.60,
    "POOR": 0.45,
}

# Opaque operator identities used by the scenario fixtures.
RM_OPERATOR_ID = "rm_1"
CO_OPERATOR_ID = "co_1"
CO_OPERATOR_ALT_ID = "co_2"

# A well-formed UUID that resolves to nothing.
UNKNOWN_UUID = "11111111-2222-4333-8444-555555555555"

# Standard timeline anchors used by the composite fixtures.
T_SECURE = "2026-05-16T00:00:00Z"          # cure expired, assignment accepted + secured
T_CONSIGN = "2026-05-27T00:00:00Z"         # redemption window lapsed
T_SALE = "2026-06-05T00:00:00Z"            # hammer reported and certified
LISTING_START = "2026-05-28T00:00:00Z"
LISTING_END = "2026-05-30T00:00:00Z"
