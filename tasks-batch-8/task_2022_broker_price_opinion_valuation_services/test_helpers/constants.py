"""Domain thresholds and shared constants (PRD §2.5, §3.1, §3.3, §3.5-§3.8)."""

# Logical clock startup instant (PRD §2.10).
CLOCK_START = "2026-08-01T00:00:00Z"

# License expiry comfortably in the future relative to CLOCK_START.
LICENSE_EXPIRES_FUTURE = "2027-01-01T00:00:00Z"

# Client account commercial terms (PRD §3.1).
DEFAULT_LATE_PENALTY_BPS_PER_DAY = 250
DEFAULT_WEIGHT_TURNAROUND = 0.5
DEFAULT_WEIGHT_QUALITY = 0.3
DEFAULT_WEIGHT_REVISION = 0.2
SLA_HOURS_STANDARD_MIN = 24
SLA_HOURS_STANDARD_MAX = 240
SLA_HOURS_RUSH_MIN = 4
MAX_LATE_PENALTY_BPS_PER_DAY = 2000

# Comparable-count floors at report submission (PRD §3.6).
COMPARABLE_FLOOR = {"DRIVE_BY": 3, "INTERIOR": 4}

# Photo-evidence minimums at report submission (PRD §3.6).
DRIVE_BY_PHOTO_KINDS = ("FRONT", "STREET")
INTERIOR_PHOTO_KINDS = ("INTERIOR_LIVING", "INTERIOR_KITCHEN", "INTERIOR_BATH")

# Comparable adjustment cap (PRD §3.5): |adjustment_cents| <= 25% of sale price.
ADJUSTMENT_CAP_PCT = 0.25

# Late-fee arithmetic (PRD §3.7).
SECONDS_PER_DAY = 86400

# Broker composite score (PRD §3.3).
SCORE_WINDOW_DAYS = 90
DECLINE_PENALTY_PTS = 1.0
SUSPEND_THRESHOLD = 50.0

# Broker concurrent-order capacity bounds (PRD §3.3).
MAX_CONCURRENT_ORDERS_MIN = 1
MAX_CONCURRENT_ORDERS_MAX = 50

# States that count against a broker's concurrent-order load (PRD §3.4).
OPEN_ORDER_STATES = (
    "DISPATCHED",
    "IN_PROGRESS",
    "REPORT_SUBMITTED",
    "QC_REVIEW",
    "REVISION_REQUESTED",
)

# Default money/geometry values used by payload factories.
DEFAULT_AGREED_FEE_CENTS = 10000
DEFAULT_COMP_SALE_PRICE_CENTS = 30000000
DEFAULT_COMP_DISTANCE_MILES = 1.5
DEFAULT_COMP_SALE_DATE = "2026-06-01T00:00:00Z"
DEFAULT_PHOTO_CAPTURED_AT = CLOCK_START
