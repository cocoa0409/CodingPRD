"""Business constants for the Draft & Combine Operations API.

Values come from the product contract: pagination limits, the logical clock
startup default, the draft-order lottery cap, slotted rookie contract money,
the trade value chart, compensatory scoring, the selection clock, medical
share windows and the UDFA pool.
"""

# ---------------------------------------------------------------------------
# Envelope and pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100

REQUEST_ID_PREFIX = "req_"

RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Draft order ranking / lottery
# ---------------------------------------------------------------------------

LOTTERY_SLOT_CAP = 4

# ---------------------------------------------------------------------------
# Combine invitation selection
# ---------------------------------------------------------------------------

INVITATION_MAX_TARGET_COUNT = 320

# ---------------------------------------------------------------------------
# Slotted rookie contract value
# ---------------------------------------------------------------------------

ROUND_BASE_CENTS = {
    1: 120000000,
    2: 100000000,
    3: 92000000,
    4: 88000000,
    5: 85000000,
    6: 82000000,
    7: 80000000,
}
SLOT_DECREMENT_CENTS = {
    1: 2000000,
    2: 800000,
    3: 400000,
    4: 200000,
    5: 120000,
    6: 80000,
    7: 40000,
}
ESCALATOR_PCT = 0.0425
CONTRACT_YEARS_DRAFTED = 4
CONTRACT_YEARS_UDFA = 3
BONUS_SHARE_PCT = {
    1: 0.60,
    2: 0.40,
    3: 0.25,
    4: 0.15,
    5: 0.10,
    6: 0.08,
    7: 0.05,
}

# ---------------------------------------------------------------------------
# Pick trade value balance
# ---------------------------------------------------------------------------

CHART_ROUND_BASE = {
    1: 1000.0,
    2: 420.0,
    3: 250.0,
    4: 150.0,
    5: 90.0,
    6: 50.0,
    7: 25.0,
}
CHART_DECAY = 0.94
TRADE_TOLERANCE_RATIO = 0.15
TRADE_TIER_FULL_MIN = 1200.0
TRADE_TIER_LIMITED_MIN = 900.0
SURPLUS_UNIT_CENTS = 1000000
POSITIONAL_MARKET_APY_CENTS = {
    1: 2200000000,
    2: 1400000000,
    3: 900000000,
    4: 700000000,
    5: 560000000,
    6: 480000000,
    7: 420000000,
}

# ---------------------------------------------------------------------------
# Compensatory pick award score
# ---------------------------------------------------------------------------

COMP_APY_UNIT_CENTS = 1000000
COMP_QUALIFY_SCORE_MIN = 250.00
COMP_MAX_AWARDS_PER_CLUB = 4
COMP_LEAGUE_MAX_AWARDS = 8

# ---------------------------------------------------------------------------
# Selection clock
# ---------------------------------------------------------------------------

ROUND_CLOCK_MINUTES = {1: 10, 2: 7, 3: 5, 4: 5, 5: 5, 6: 5, 7: 4}
TIMEOUT_EXTENSION_MINUTES = 2
CLOCK_COMPRESSION_MINUTES = 1
COMPRESSION_FIRST_ROUND = 5
CLUB_TIMEOUTS_PER_CYCLE = 2

# ---------------------------------------------------------------------------
# Medical share access window
# ---------------------------------------------------------------------------

MEDICAL_SHARE_TTL_DAYS = 75
MEDICAL_SHARE_DRAFT_GRACE_DAYS = 3

# ---------------------------------------------------------------------------
# UDFA pool allocation
# ---------------------------------------------------------------------------

UDFA_BASE_POOL_CENTS = 40000000
UDFA_ROLLOVER_PCT = 0.10
UDFA_TIER_LOW_MIN = 120000000
UDFA_TIER_MID_MIN = 60000000
UDFA_CREDIT_RATE_LOW = 0.25
UDFA_CREDIT_RATE_MID = 0.40
UDFA_CREDIT_RATE_HIGH = 0.55
UDFA_WINDOW_HOURS = 72

# ---------------------------------------------------------------------------
# Booking conflict allowances
# ---------------------------------------------------------------------------

PROSPECT_TRAVEL_ALLOWANCE_MINUTES = 10
DEFAULT_STATION_TURNAROUND_BUFFER_MINUTES = 15
DEFAULT_ROOM_CONCURRENT_CAPACITY = 2
BOOKING_CHECK_IN_LEAD_MINUTES = 30

# ---------------------------------------------------------------------------
# Canonical scenario instants (2027 cycle used across the suite)
# ---------------------------------------------------------------------------

SEASON_YEAR = 2027
CYCLE_SETUP_NOW = "2027-01-02T00:00:00.000Z"
DECLARATION_DEADLINE_AT = "2027-01-15T23:59:59.000Z"
COMBINE_WEEK_START_AT = "2027-02-22T08:00:00.000Z"
COMBINE_WEEK_END_AT = "2027-02-28T20:00:00.000Z"
DRAFT_START_AT = "2027-04-22T18:00:00.000Z"
UDFA_WINDOW_CLOSE_AT = "2027-04-25T18:00:00.000Z"
