"""Domain constants and thresholds declared by the PRD.

Every literal here is stated in the PRD narrative; nothing is inferred.
"""

# --- Logical clock -----------------------------------------------------------
# The clock's mandatory value before it has ever been set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Line posture ------------------------------------------------------------
# A line whose free_slot_pct is strictly below this is CONSTRAINED.
POSTURE_CONSTRAINED_PCT = 20.00

# --- Shift labour ------------------------------------------------------------
SHIFT_MINUTES = 480            # base available labour minutes for every shift
OVERTIME_CAP_MINUTES = 120     # inclusive upper bound on overtime_minutes
CHANGEOVER_MINUTES = 18        # booked per family boundary and per line start
FATIGUE_T1_MAX = 300           # gross minutes at or below this use FATIGUE_T1
FATIGUE_T2_MAX = 450           # gross minutes at or below this use FATIGUE_T2
FATIGUE_T1 = 1.00
FATIGUE_T2 = 1.05
FATIGUE_T3 = 1.12

# Canonical shift windows, keyed by shift_code.
SHIFT_WINDOWS = {
    "A": ("06:00", "14:00"),
    "B": ("14:00", "22:00"),
    "C": ("22:00", "06:00"),    # C ends at 06:00 the following day
}

# --- Option load window ------------------------------------------------------
LOAD_WINDOW_SLOTS = 5          # rolling window length in sequence positions
MAX_POINTS_PER_SLOT = 10       # ceiling on option_content_points

# --- Presentation slots ------------------------------------------------------
PRESENTATION_WINDOW_UNITS = 20  # units of line-side presentation coverage

# --- Delivery dock -----------------------------------------------------------
DOCK_BUFFER_MINUTES = 10       # symmetric pad applied to a candidate window
MISS_GRACE_MINUTES = 15        # grace after window_end before a call is MISSED

# --- Supplier scoring --------------------------------------------------------
SCORE_START = 100.00
ON_TIME_BONUS = 2
LATE_PENALTY = 8
MISS_PENALTY = 20
QUALITY_PENALTY = 10
SCORE_CAP = 100.00
SCORE_FLOOR = 0.00
APPROVED_MIN = 60.00           # score at or above this is APPROVED
PROBATION_MIN = 40.00          # score at or above this (but below APPROVED_MIN)

# --- Efficiency index --------------------------------------------------------
ENERGY_WEIGHT = 0.6
WATER_WEIGHT = 0.4
TIER_A_PLUS_MAX = 0.80
TIER_A_MAX = 0.95
TIER_B_MAX = 1.00              # strictly above this is not certifiable

# --- Engineering change ------------------------------------------------------
EC_MAX_REVISION_ROUNDS = 3
SERVICE_OBLIGATION_YEARS = 10

# --- Warranty ---------------------------------------------------------------
RATE_BASE_UNITS = 1000
EXPECTED_ANNUAL_HOURS = 2000
WARRANTY_RATE_TRIGGER = 8.00

# --- Numeric tolerance -------------------------------------------------------
# Money-free ratios are carried at two decimal places; comparisons use this.
CENT = 0.01
