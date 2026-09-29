"""Numeric and temporal constants the PRD pins for the junior golf tour."""

# ------------------------------------------------------------- clock (2.5)
PROCESS_START_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------- pagination (2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------- handicaps (3.1)
HANDICAP_INDEX_MIN = -5.0
HANDICAP_INDEX_MAX = 54.0
HANDICAP_VALIDITY_DAYS = 180

# ----------------------------------------------------------- divisions (3.1)
DIVISION_BANDS = (
    (11, 13, "U13"),
    (14, 15, "U15"),
    (16, 17, "U17"),
    (18, 19, "U19"),
)

# ------------------------------------------------------------ scoring (3.6)
GROSS_STROKES_MIN = 50
GROSS_STROKES_MAX = 130
DIFFERENTIAL_STANDARD_SLOPE = 113
SLOPE_RATING_MIN = 55
SLOPE_RATING_MAX = 155

# --------------------------------------------------------------- pace (3.6)
PACE_FREE_WARNINGS = 2
PACE_TIMING_BREACH_MINUTES = 15
PACE_TIMING_COMPONENT = 2
PACE_PENALTY_CAP = 3

# ------------------------------------------------------ rules cases (3.7)
MAX_DISPUTES = 3
CERTIFIED_REOPEN_WINDOW_HOURS = 48
RULES_APPEAL_WINDOW_HOURS = 72
PENALTY_STROKES_MIN = 0
PENALTY_STROKES_MAX = 8

# ----------------------------------------------------------- money (3.3/3.4)
PER_MEMBER_CAP_CENTS = 60000
LATE_SURCHARGE_WINDOW_HOURS = 72
LATE_SURCHARGE_RATE = 0.10
ASSISTANCE_ESTIMATE_BASIS_CENTS = 25000

# income_per_dependent_cents ceiling -> covered_pct
COVERED_PCT_BANDS = (
    (1500000, 1.00),
    (2500000, 0.90),
    (4500000, 0.65),
    (7000000, 0.40),
)
COVERED_PCT_INELIGIBLE = 0.00

# ------------------------------------------------------ field quality (3.5)
FIELD_QUALITY_BASE = 1.00
FIELD_QUALITY_ELITE_RANK_CUTOFF = 50
FIELD_QUALITY_ELITE_WEIGHT = 0.02
FIELD_QUALITY_DEPTH_FLOOR = 12
FIELD_QUALITY_DEPTH_WEIGHT = 0.01
FIELD_QUALITY_CAP = 1.60

# ------------------------------------------------------- event points (3.8)
TIER_BASE_POINTS = {
    "LOCAL": 150,
    "REGIONAL": 300,
    "NATIONAL": 600,
    "INVITATIONAL": 800,
}
FINISH_FACTOR_STEP = 0.05
FINISH_FACTOR_FLOOR = 0.20
DIFFERENTIAL_BONUS_PIVOT = 2.0
DIFFERENTIAL_BONUS_WEIGHT = 25

# ---------------------------------------------------------- rankings (3.8)
CERTIFIED_COUNTING_EVENTS = 4

# ----------------------------------------------------------- conduct (3.9)
INCIDENT_POINTS = {
    "SPECTATOR_INTERFERENCE": 2,
    "COACHING_VIOLATION": 2,
    "ABUSIVE_LANGUAGE": 3,
    "CADDIE_ADVICE_BREACH": 2,
    "PHYSICAL_ALTERCATION": 6,
    "SCORE_TAMPERING": 6,
}
CONDUCT_DECAY_WINDOW_DAYS = 365
CONDUCT_WARNING_CEILING = 3
CONDUCT_SUSPENSION_FLOOR = 6
CONDUCT_APPEAL_WINDOW_DAYS = 14
LATE_WITHDRAWAL_BAND_THRESHOLD = 2

# --------------------------------------------------- recruiting access (3.9)
COACH_GRANT_VALIDITY_DAYS = 180

# --------------------------------------------- shared scenario literals (3.x)
SEASON_NAME = "2026 Junior Tour"
SEASON_START_DATE = "2026-01-01"
SEASON_END_DATE = "2026-12-31"
SEASON_AGE_CUTOFF_DATE = "2026-08-31"
SEASON_RANKING_WINDOW_START_DATE = "2026-01-01"
SEASON_ASSISTANCE_BUDGET_CENTS = 500000

COURSE_RATING = 71.4
SLOPE_RATING = 128
STANDARD_ENTRY_FEE_CENTS = 25000
