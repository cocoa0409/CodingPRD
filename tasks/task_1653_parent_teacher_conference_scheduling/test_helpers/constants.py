"""Domain thresholds and standard fixtures — numeric constants from PRD 3."""

# Slot-grid generation (PRD 3.2): a break is inserted after every fourth slot.
BREAK_EVERY = 4
BREAK_EXTRA_MINUTES = 15

# Interpreter capacity (PRD 3.7): ten-minute break allowance per full
# forty-five-minute block of committed minutes.
RUN_LENGTH_MINUTES = 45
BREAK_ALLOWANCE_PER_RUN = 10

# Interpreter pay (PRD 3.7): billable units are fifteen minutes.
BILL_UNIT_MINUTES = 15

# Waitlist offers (PRD 3.6): an entry is EXHAUSTED once it has consumed 2 offers.
MAX_OFFERS = 2

# Utilization projection (PRD 3.9): half the waiting entries, rounded up.
WAITLIST_CLAIM_RATE = 0.5

# Waitlist priority score weights (PRD 3.6).
PRIORITY_BASE = 100
PRIORITY_REQUIRED_BONUS = 50
PRIORITY_SIBLING_BONUS = 15
PRIORITY_SIBLING_CAP = 2
PRIORITY_RISK_PENALTY_PER_POINT = 10
PRIORITY_RISK_CAP = 5
PRIORITY_WAIT_BONUS_PER_DAY = 5
PRIORITY_WAIT_CAP_DAYS = 4

# Compactness tiers (PRD 3.4).
COMPACT_TIER1_MAX_MIN = 15
COMPACT_TIER1_PTS = 1
COMPACT_TIER2_MAX_MIN = 45
COMPACT_TIER2_PTS = 3
COMPACT_TIER3_PTS = 8
COMPACT_CHANNEL_SWITCH_MULT = 2

# Family risk weights (PRD 3.8).
RISK_W_NO_SHOW = 1.0
RISK_W_LATE = 0.5
RISK_W_EXCUSED = 0.25

# Default logical-clock reading before any set call (PRD 2.4).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
# Standard clock used to sit inside the booking-open period.
CLOCK_OPEN = "2026-09-01T00:00:00Z"
# Clock used to pass booking_close_at for the standard window.
CLOCK_CLOSE = "2026-10-02T00:00:00Z"
# Clock used on conference day, after the first slot has started.
CLOCK_CONFERENCE = "2026-10-05T15:30:00Z"

# Standard window geometry (PRD 3.1): 20-minute slots, 5-minute buffer,
# 30-minute travel, one day window 2026-10-05 15:00-19:00Z, which yields
# exactly 8 slots per eligible teacher.
STD_SLOT_LENGTH = 20
STD_BUFFER = 5
STD_TRAVEL = 30
STD_DAY = {
    "date": "2026-10-05",
    "start_at": "2026-10-05T15:00:00Z",
    "end_at": "2026-10-05T19:00:00Z",
}
STD_SLOTS_PER_TEACHER = 8
STD_BOOKING_OPEN_AT = "2026-09-01T00:00:00Z"
STD_BOOKING_CLOSE_AT = "2026-10-01T00:00:00Z"

# Well-formed UUID that never resolves to a stored resource.
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
