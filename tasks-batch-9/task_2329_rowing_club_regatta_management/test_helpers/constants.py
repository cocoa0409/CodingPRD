"""Domain thresholds and pinned numeric constants from the PRD.

Every value here is quoted from PRD prose (§2.5, §2.6, §3.1-§3.9). Nothing is
invented: if the PRD does not pin a number, it does not appear in this file.
"""

# --- §2.5 The logical clock -------------------------------------------------
# "Before that capability is ever called, the logical clock reads exactly
#  2026-08-01T00:00:00Z"
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# --- §3.2 Dues assessment ---------------------------------------------------
TIER_SEASON_FEE_CENTS = {
    "COMPETITIVE": 95000,
    "RECREATIONAL": 61500,
    "LEARN_TO_ROW": 35500,
}
TIER_ACCESS_SURCHARGE_CENTS = {
    "COMPETITIVE": 23500,
    "RECREATIONAL": 12500,
    "LEARN_TO_ROW": 0,
}
LOCKER_FEE_CENTS = 8750
SEASON_MONTHS = 12

# --- §3.2 End-of-season true-up --------------------------------------------
TRUEUP_PER_SESSION_CENTS = 4500
TRUEUP_FLOOR_FACTOR = 0.40
TRUEUP_ADMIN_FEE_CENTS = 5000

# --- §3.3 Fleet: rack units, severity weights, decay ------------------------
CLASS_SLOT_UNITS = {"1X": 1, "2X": 1, "4+": 2, "8+": 3}
CLASS_MAX_TIER = {"1X": 4, "2X": 4, "4+": 2, "8+": 1}
CLASS_SEAT_COUNT = {"1X": 1, "2X": 2, "4+": 5, "8+": 9}

SEVERITY_WEIGHT_POINTS = {
    "COSMETIC": 2.0,
    "MINOR": 6.0,
    "MAJOR": 18.0,
    "STRUCTURAL": 40.0,
}
DECAY_PERIOD_DAYS = 30
DECAY_POINTS_PER_PERIOD = 0.5
VERIFIED_RESIDUAL_FACTOR = 0.25
CONDITION_INDEX_CEILING = 100
MIN_CONDITION_INDEX_TO_RACE = 60

# --- §3.4 River conditions and launch coverage ------------------------------
COLD_WATER_TEMP_C = 12.8            # strictly below
COLD_COMBINED_SUM_C = 30.0          # at or below
WIND_CLOSE_KT = 20.0                # at or above -> CLOSED
VIS_CLOSE_M = 400                   # at or below -> CLOSED
WIND_RESTRICT_KT = 12.0             # at or above -> RESTRICTED
VIS_RESTRICT_M = 800                # at or below -> RESTRICTED
MAX_LAUNCHES_PER_SESSION = 2
SHELL_TURNAROUND_BUFFER_MINUTES = 30
SWIM_TEST_VALID_DAYS = 365

# --- §3.6 Entry fees, weigh-ins, refunds ------------------------------------
CLASS_ENTRY_FEE_CENTS = {"1X": 4500, "2X": 7500, "4+": 13500, "8+": 25000}
TRANSPORT_LEVY_PER_UNIT_CENTS = 5000
LATE_FEE_SUBTOTAL_THRESHOLD_CENTS = 25000
LATE_FEE_PCT_HIGH = 0.15
LATE_FEE_PCT_LOW = 0.10
MIN_COXSWAIN_WEIGHT_KG = 55.0
MAX_ENTRY_DEADWEIGHT_KG = 15.0
REFUND_PCT_FULL = 1.00
REFUND_PCT_PARTIAL = 0.55
REFUND_PCT_NONE = 0.00

# --- §3.7 Trailer rack geometry --------------------------------------------
DEFAULT_RACK_TIER_COUNT = 4
DEFAULT_RACK_UNITS_PER_TIER = 4
DEFAULT_RACK_UNIT_CAPACITY = DEFAULT_RACK_TIER_COUNT * DEFAULT_RACK_UNITS_PER_TIER

# --- §3.8 Lane assignment ---------------------------------------------------
LANE_PREFERENCE_ORDER = [3, 4, 2, 5, 1, 6, 7, 8]

# --- §3.9 Jury ------------------------------------------------------------
PROTEST_DEPOSIT_CENTS = 5000
PROTEST_WINDOW_MINUTES = 30
MAX_JURY_ROUNDS = 2

# --- Convenient scenario instants used by the composite fixtures ------------
# These are ordinary payload values, not PRD constants; they keep the fixture
# timeline readable.
CLOCK_SEASON_START = "2026-08-01T00:00:00Z"
REGATTA_RACE_DATE = "2026-08-12T08:00:00Z"
REGATTA_ENTRY_DEADLINE = "2026-08-10T00:00:00Z"
REGATTA_SCRATCH_DEADLINE = "2026-08-11T00:00:00Z"
REGATTA_WEIGH_IN_OPENS = "2026-08-12T06:00:00Z"
REGATTA_WEIGH_IN_CLOSES = "2026-08-12T07:00:00Z"
RACE_DAY_MORNING = "2026-08-12T09:00:00Z"
CURRENT_SWIM_TEST = "2026-04-01T00:00:00Z"
FAR_FUTURE_CERT = "2027-01-01T00:00:00Z"
