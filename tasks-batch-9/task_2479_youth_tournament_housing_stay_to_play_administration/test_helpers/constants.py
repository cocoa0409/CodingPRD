"""Literal thresholds, tiers and defaults quoted from the PRD.

Every value here is a number the PRD states outright, so a test can assert
against a named constant instead of a bare magic number.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

# PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`."
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Roster occupancy variants (PRD §3.3)
# ---------------------------------------------------------------------------

# The segregated booking variant: players four to a room, staff two to a room.
PLAYERS_PER_ROOM_SEGREGATED = 4
STAFF_PER_ROOM_SEGREGATED = 2
# The pooled compliance variant: the whole travelling party four to a room.
OCCUPANTS_PER_ROOM_POOLED = 4

# PRD §3.3 local radius.
LOCAL_TEAM_RADIUS_MILES = 30.0


# ---------------------------------------------------------------------------
# Room blocks (PRD §3.2, §3.4)
# ---------------------------------------------------------------------------

# The padded event window extends the tournament dates by two days each side.
BLOCK_WINDOW_PAD_DAYS = 2
# A block whose utilization reaches this fraction becomes RESTRICTED.
BLOCK_RESTRICTION_UTILIZATION_PCT = 0.90
# Utilization is carried to four decimals.
UTILIZATION_DECIMALS = 4
# A block is TIGHT/SOLD_OUT relative to this same utilization threshold.
ROOM_OCCUPANCY_LIMIT = 4


# ---------------------------------------------------------------------------
# Cancellation penalty tiers (PRD §3.5)
# ---------------------------------------------------------------------------

CANCEL_FREE_TIER_DAYS = 45
CANCEL_QUARTER_TIER_DAYS = 21
CANCEL_HALF_TIER_DAYS = 7
CANCEL_QUARTER_FRACTION = 0.25
CANCEL_HALF_FRACTION = 0.50


# ---------------------------------------------------------------------------
# Tiered rebate rates (PRD §3.7)
# ---------------------------------------------------------------------------

REBATE_TIER_LOW_MAX_NIGHTS = 30
REBATE_TIER_MID_MAX_NIGHTS = 90
REBATE_TIER_LOW_CENTS = 500
REBATE_TIER_MID_CENTS = 750
REBATE_TIER_HIGH_CENTS = 1000


# ---------------------------------------------------------------------------
# Administrative fee tiers (PRD §3.9)
# ---------------------------------------------------------------------------

ADMIN_FEE_LOW_MAX_CENTS = 50000
ADMIN_FEE_MID_MAX_CENTS = 200000
ADMIN_FEE_PCT_LOW = 0.08
ADMIN_FEE_PCT_MID = 0.06
ADMIN_FEE_PCT_HIGH = 0.045


# ---------------------------------------------------------------------------
# Remedies and appeals (PRD §3.6, §3.9)
# ---------------------------------------------------------------------------

RATE_ADJUSTMENT_FRACTION = 0.10
MAX_EXCEPTION_APPEALS = 1


# ---------------------------------------------------------------------------
# System literals
# ---------------------------------------------------------------------------

# PRD §3.6/§3.7: the actor recorded when the system itself decides.
SYSTEM_AUTO = "SYSTEM_AUTO"
# PRD §3.7: the note stamped on requests denied by the close cascade.
CLOSED_WITHOUT_DECISION = "closed without decision"
