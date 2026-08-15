"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default and standard meet/session timetable used by fixtures.
CLOCK_START = "2026-05-01T00:00:00Z"
MEET_START = "2026-05-02T08:00:00Z"
MEET_END = "2026-05-02T22:00:00Z"
SESSION_START = "2026-05-02T14:00:00Z"
SESSION_END = "2026-05-02T18:00:00Z"

APPARATUS_ORDER = ["VAULT", "UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE"]

# Rotation pacing (PRD: per-athlete pace in seconds by apparatus).
PER_ATHLETE_SECONDS = {
    "VAULT": 30,
    "UNEVEN_BARS": 90,
    "BALANCE_BEAM": 120,
    "FLOOR_EXERCISE": 90,
}
CHANGEOVER_GAP_MINUTES = 5

# Warm-up block layout constants.
WARMUP_WINDOW_MINUTES = 60
MIN_BLOCK_MINUTES = 8
MAX_BLOCK_MINUTES = 20
PER_ATHLETE_WARMUP_MINUTES = 2

# Judge panel staffing (USAG rule): BB/FX need 4, VT/UB need 2.
REQUIRED_JUDGE_COUNT = {
    "BALANCE_BEAM": 4,
    "FLOOR_EXERCISE": 4,
    "VAULT": 2,
    "UNEVEN_BARS": 2,
}

# Qualification mobility thresholds (inclusive lower bounds).
L45_STATE_AA = 32.000
L678_STATE_AA = 34.000
L678_REGIONAL_AA = 35.500
L910_STATE_AA = 34.500
L910_REGIONAL_AA = 36.000
L10_NATIONAL_AA = 37.500
EVENT_STATE_THRESHOLD = 9.000

# Score input ranges.
SCORE_MAX = 10.000
DEDUCTION_MAX = 5.000

# Inquiry delta bounds.
D_E_DELTA_RANGE = (-2.000, 2.000)
DEDUCTION_DELTA_RANGE = (-5.000, 0.000)

# Meet policy defaults.
DEFAULT_TIEBREAK_POLICY = "USAG_CLASSIC"
DEFAULT_QUALIFYING_SCORE_RULE = "BOTH"
DEFAULT_INQUIRY_WINDOW_MINUTES = 5
DEFAULT_MAX_ATHLETES_PER_SQUAD = 12
