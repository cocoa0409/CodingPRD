"""Numeric and temporal constants the PRD pins for this domain."""

API_PREFIX = "/recreation"

# --- Logical clock ---------------------------------------------------------
# "the clock starts at exactly 2026-08-01T00:00:00Z" on a fresh server.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Supervision weighting -------------------------------------------------
COGNITION_BAND = {
    "INTACT": 1,
    "MILD_IMPAIRMENT": 1,
    "MODERATE_IMPAIRMENT": 2,
    "SEVERE_IMPAIRMENT": 3,
}
FUNCTION_BAND = {
    "INDEPENDENT": 1,
    "ASSIST_1": 1,
    "ASSIST_2": 2,
    "WHEELCHAIR_DEPENDENT": 2,
    "BEDBOUND": 3,
}
TIER_WEIGHT = {"TIER_1": 1.0, "TIER_2": 1.5, "TIER_3": 3.0}
BAND_TO_TIER = {1: "TIER_1", 2: "TIER_2", 3: "TIER_3"}

# --- Plans and attainment --------------------------------------------------
CYCLE_DAYS = 28
DOMAIN_TARGET_MIN = 0
DOMAIN_TARGET_MAX = 20
CREDITED_ENGAGEMENT_LEVELS = ["PARTIAL", "ACTIVE", "LEADING"]
OFFERED_OUTCOMES = ["ATTENDED", "REFUSED"]

# --- Engagement and refusal ------------------------------------------------
ENGAGEMENT_POINTS = {
    "NONE": 0,
    "PASSIVE_OBSERVER": 1,
    "PARTIAL": 2,
    "ACTIVE": 3,
    "LEADING": 4,
}
MAX_ENGAGEMENT_POINTS = 4
ENGAGEMENT_WINDOW_SIZE = 10
REFUSAL_REVIEW_THRESHOLD = 3

# --- Volunteers ------------------------------------------------------------
BACKGROUND_CHECK_VALID_DAYS = 365
WEEKLY_HOUR_CAP = 8.00
SCREENING_RANK = {"NONE": 0, "BASIC": 1, "FULL": 2}
INTERGENERATIONAL_MIN_STAFF = 2

# --- Outings ---------------------------------------------------------------
OUTING_RATIO_DENOMINATOR = 4
TIER_3_ESCORT_FLOOR = 2
MAX_STATION_CONVERSIONS = 2
DEFAULT_TURNAROUND_MINUTES = 30

# --- Council and survey ----------------------------------------------------
COUNCIL_QUORUM = 5
DOMAIN_PENALTY_PER_UNMET = 5.0
REFUSAL_PENALTY_PER_RESIDENT = 2.0
FLAG_DEDUCTION = 3.0
F248_THRESHOLD = 50.0

# --- Probe identifiers that are well-formed UUIDs but resolve to nothing ---
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
ABSENT_UUID_2 = "00000000-0000-4000-8000-0000000000ff"
ABSENT_UUID_3 = "00000000-0000-4000-8000-0000000000aa"
ABSENT_UUID_4 = "00000000-0000-4000-8000-0000000000bb"
ABSENT_UUID_5 = "00000000-0000-4000-8000-0000000000cc"
ABSENT_UUID_6 = "00000000-0000-4000-8000-0000000000dd"
ABSENT_UUID_7 = "00000000-0000-4000-8000-0000000000ee"
ABSENT_UUID_8 = "00000000-0000-4000-8000-000000000011"
ABSENT_UUID_9 = "00000000-0000-4000-8000-000000000022"
