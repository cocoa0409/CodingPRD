"""Domain thresholds and reproducible literals from the PRD.

Every numeric constant here is quoted from PRD section 2.5 (rating arithmetic),
section 3.2 (rating formulas), section 3.6 (staffing coverage) and section 3.9
(scoring, penalties and discards).
"""

# ── Rating arithmetic (PRD 3.2) ────────────────────────────────────────────
LENGTH_DIVISOR = 8.0
LENGTH_FACTOR_FLOOR = 1.00
LENGTH_FACTOR_CEIL = 1.60
DEEP_DRAFT_THRESHOLD_M = 2.20
DEEP_DRAFT_MULTIPLIER = 0.97
NO_PENALTY_MULTIPLIER = 1.00

HULL_FAMILY_MULTIPLIER = {
    "MONOHULL": 1.00,
    "MULTIHULL": 0.82,
    "KEELBOAT_SPORT": 0.94,
}

RAW_SPEED_INDEX_DECIMALS = 4

TOD_INTERCEPT = 420.0
TOD_SLOPE = 380.0
TOD_CLAMP_LOW = -30.0
TOD_CLAMP_HIGH = 300.0

TOT_INTERCEPT = 0.4000
TOT_SLOPE = 0.7000
TOT_CLAMP_LOW = 0.5000
TOT_CLAMP_HIGH = 1.6000
BAND_KEY_SLOPE = 542.8571

# ── Measurement input ranges (PRD 3.2) ─────────────────────────────────────
MAX_SAIL_AREA_M2 = 400
MAX_HULL_LENGTH_M = 40
MAX_DISPLACEMENT_KG = 100000
MAX_DRAFT_M = 6
MAX_LOA_METERS = 40

# ── Scoring (PRD 3.9) ──────────────────────────────────────────────────────
BONUS_POINT_TABLE = {1: 0.0, 2: 3.0, 3: 5.7, 4: 8.0, 5: 10.0, 6: 11.7}
BONUS_TAIL_OFFSET = 6.0
NON_FINISHER_EXTRA = 1
DNC_EXTRA = 2
ACCEPTED_PENALTY_PERCENTS = [0, 20, 30, 40]
MAX_ELAPSED_SECONDS = 604800
MAX_COURSE_DISTANCE_NM = 300

DISCARD_ONE_PER_FIVE_THRESHOLD = 5
DISCARD_ONE_PER_FOUR_DIVISOR = 4
DISCARD_ONE_PER_FOUR_CAP = 2

# ── Staffing coverage window (PRD 3.6) ─────────────────────────────────────
PRESTART_COVERAGE_MINUTES = 30
POSTSTART_COVERAGE_MINUTES = 120
ALWAYS_REQUIRED_POSITIONS = ["PRO", "SIGNALS", "TIMEKEEPER"]
MARK_BOAT_COURSES = ["WINDWARD_LEEWARD", "TRIANGLE"]
SAFETY_BOAT_CATEGORIES = ["CAT_3", "CAT_2"]

# ── Start line occupancy (PRD 3.7) ─────────────────────────────────────────
PRESTART_WINDOW_MINUTES = 5
START_LINE_GAP_MINUTES = 3

# ── Declared defaults (PRD 3.1, 3.3, 3.4, 3.6) ─────────────────────────────
DEFAULT_JUDGE_CERTIFICATION_LEVEL = "NONE"
DEFAULT_ASSIGNED_DUTY_MINUTES = 0
DEFAULT_DISCARD_POLICY = "NONE"
DEFAULT_HANDICAP_BASIS = "PER_CERTIFICATE"
DEFAULT_FLEET_MINIMUM = 3
DEFAULT_PROTEST_TIME_LIMIT_MINUTES = 90
DEFAULT_JURY_QUORUM_REQUIRED = 3
DEFAULT_MIN_ENTRIES = 3
DEFAULT_CONCURRENT_ASSIGNMENT_LIMIT = 2
DEFAULT_TURNAROUND_BUFFER_MINUTES = 20
DEFAULT_PENALTY_PERCENT = 0

# ── Pagination (PRD 2.3) ───────────────────────────────────────────────────
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100

# ── Logical clock (PRD 2.4) ────────────────────────────────────────────────
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ── Reproducible world literals used by the composite fixtures ─────────────
CERT_VALID_FROM = "2026-01-01T00:00:00Z"
CERT_VALID_UNTIL = "2026-12-31T00:00:00Z"
SERIES_START_UTC = "2026-08-05T00:00:00Z"
SAFETY_COURSE_OK_UNTIL = "2027-06-30T00:00:00Z"

NOR_EFFECTIVE_UTC = "2026-07-10T00:00:00Z"
SI_EFFECTIVE_UTC = "2026-07-15T00:00:00Z"

RACE_DAY = "2026-08-05"
DUTY_WINDOW_START = "2026-08-05T12:00:00Z"
DUTY_WINDOW_END = "2026-08-05T20:00:00Z"
RACE_1_SCHEDULED_START = "2026-08-05T14:00:00Z"

# A path identifier that resolves to nothing, for the 404 probes.
UNKNOWN_UUID = "00000000-0000-4000-8000-0000000000ff"

# Boat measurement sets whose rating values are pinned by the PRD formulas.
#   BOAT_A: raw 0.6545 → TOD_PHRF rating 171.3 / band 171.3
#                      → TOT_ORC  rating 0.8582 / band 171.3
#   BOAT_B: raw 0.5294 → TOD_PHRF rating 218.8 / band 218.8
#   BOAT_D: raw 0.5767 → TOD_PHRF rating 200.9 / band 200.9
#                      → TOT_ORC  rating 0.8037 / band 200.8
MEASUREMENT_A = {
    "sail_area_m2": 68.0,
    "hull_length_m": 11.0,
    "displacement_kg": 5200,
    "draft_m": 2.10,
}
MEASUREMENT_B = {
    "sail_area_m2": 52.0,
    "hull_length_m": 9.4,
    "displacement_kg": 4100,
    "draft_m": 1.95,
}
MEASUREMENT_D = {
    "sail_area_m2": 61.0,
    "hull_length_m": 10.2,
    "displacement_kg": 4700,
    "draft_m": 2.35,
}

RATING_A_TOD = 171.3
RATING_A_TOT = 0.8582
BAND_A = 171.3
RATING_B_TOD = 218.8
BAND_B = 218.8
RATING_D_TOD = 200.9
RATING_D_TOT = 0.8037
BAND_D_TOD = 200.9
BAND_D_TOT = 200.8
