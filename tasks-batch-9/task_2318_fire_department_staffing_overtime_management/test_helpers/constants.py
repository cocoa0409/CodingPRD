"""Domain constants for the fire-staffing-overtime API.

Every value here is stated verbatim in the PRD; the names mirror the PRD's own
wording so that a failing assertion points straight at the paragraph it came
from.
"""

# ---------------------------------------------------------------------------
# Logical duty clock (PRD 2.5)
# ---------------------------------------------------------------------------
# "Until that capability is called for the first time, the logical clock reads
#  2026-08-01T00:00:00Z. That default is mandatory, not illustrative."
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Rotation calendar (PRD 2.8)
# ---------------------------------------------------------------------------
ROTATION_EPOCH_DATE = "2026-01-01"
PLATOON_ORDER = ["A", "B", "C", "D"]
KELLY_CYCLE_LENGTH = 8

# Dates whose platoon / Kelly slot are fixed by the rotation calendar and are
# reused throughout the suite.
SHIFT_DATE_PLATOON_B = "2026-08-10"   # platoon B, Kelly slot 8
SHIFT_DATE_PLATOON_C = "2026-08-11"   # platoon C, Kelly slot 8
SHIFT_DATE_PLATOON_D = "2026-08-12"   # platoon D, Kelly slot 8
SHIFT_DATE_PLATOON_C_LATE = "2026-08-23"   # platoon C, Kelly slot 3
SHIFT_DATE_PLATOON_C_LATER = "2026-08-27"  # platoon C, Kelly slot 4

# ---------------------------------------------------------------------------
# Staffing derivation (PRD 2.11, 3.2)
# ---------------------------------------------------------------------------
LEAVE_FLOOR_SLACK = 2
CLOSURE_TRIGGER_GAP = 2
MAX_OVERSTAFF_SEATS = 1

# ---------------------------------------------------------------------------
# Duty hours (PRD 3.3)
# ---------------------------------------------------------------------------
SHIFT_START_HOUR = 8
SHIFT_HOURS = 24
CONTINUOUS_DUTY_FATIGUE_HOURS = 24
CONTINUOUS_DUTY_MAX_HOURS = 48

# ---------------------------------------------------------------------------
# Trades (PRD 3.5)
# ---------------------------------------------------------------------------
TRADE_LEAD_TIME_HOURS = 48

# ---------------------------------------------------------------------------
# Overtime offer pricing (PRD 2.9, 3.6)
# ---------------------------------------------------------------------------
CERT_PREMIUM_PCT = {
    "NONE": 0,
    "PARAMEDIC": 12,
    "HAZMAT_TECH": 8,
    "TECHNICAL_RESCUE": 8,
}
FATIGUE_PREMIUM_PCT = 10
MODE_MIN_HOURS = {
    "VOLUNTARY": 0,
    "MANDATORY_HOLDOVER": 2,
    "CALLBACK": 3,
}
OT_MULTIPLIER = {
    "VOLUNTARY": 1.5,
    "MANDATORY_HOLDOVER": 1.5,
    "CALLBACK": 2.0,
}

# ---------------------------------------------------------------------------
# Budget posture bands, in basis points (PRD 2.10)
# ---------------------------------------------------------------------------
WITHIN_BAND_BP = 9000
WATCH_BAND_BP = 10000

# ---------------------------------------------------------------------------
# FLSA work period (PRD 3.9)
# ---------------------------------------------------------------------------
FLSA_PERIOD_DAYS = 27
FLSA_THRESHOLD_HOURS = 204
FLSA_MAX_PERIOD_HOURS = 288
FLSA_PREMIUM_RATE = 0.5

# ---------------------------------------------------------------------------
# Overtime forecast (PRD 3.9)
# ---------------------------------------------------------------------------
INJURY_SHIFTS_PER_PERIOD = 9
OT_MULTIPLIER_VOLUNTARY = 1.5

# ---------------------------------------------------------------------------
# Academy hiring signal (PRD 3.9)
# ---------------------------------------------------------------------------
PLATOON_COVERAGE_FACTOR = 4
INJURY_BODY_WEIGHT = 2
MONITOR_MAX = 8
RECRUIT_MAX = 20

# ---------------------------------------------------------------------------
# Offer expiry sweep (PRD 3.7)
# ---------------------------------------------------------------------------
OFFER_RESPONSE_WINDOW_MINUTES = 120
OT_PASS_LIMIT = 3

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
