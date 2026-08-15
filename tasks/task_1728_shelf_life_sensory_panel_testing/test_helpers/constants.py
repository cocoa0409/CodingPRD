"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# --- Logical clock (PRD §2.4) ------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
SECONDS_PER_STUDY_DAY = 86400

# --- Fifteen-point attribute scale (PRD §3.5) --------------------------------
SCORE_MIN = 1
SCORE_MAX = 15

# --- Panelist pipeline (PRD §3.4) --------------------------------------------
ACUITY_QUALIFY_THRESHOLD = 80          # inclusive: 80 itself qualifies
ACUITY_MIN = 0
ACUITY_MAX = 100
TRAINING_SESSIONS_REQUIRED = 3
NO_SHOW_SUSPENSION_THRESHOLD = 3
REACTIVATION_CONSISTENCY_THRESHOLD = 60

# --- Session power sizing (PRD §3.5) -----------------------------------------
Z_ALPHA = 1.96
Z_BETA = 0.84
DEFAULT_VARIANCE = 2.25
MIN_PANELISTS = 4
MAX_PANELISTS = 12
SESSION_OVERBOOK_HEADROOM = 2

# --- Significance screening (PRD §3.5) ---------------------------------------
PANEL_SD = 1.5
Z_975 = 1.96

# --- Session open window (PRD §3.5) ------------------------------------------
OPEN_EARLY_MINUTES = 30

# --- Retainer reserve (PRD §3.2) ---------------------------------------------
BASE_RESERVE_HOURS = 10
PER_TIME_POINT_HOURS = 2
PER_ARM_HOURS = 4

# --- Settlement charges (PRD §3.7) -------------------------------------------
ASSIGNMENT_FEE_HOURS = 0.5
ROOM_QUANTUM_MINUTES = 15
ROOM_QUANTUM_HOURS = 0.25
TEST_HOURS = {
    "APC": 1.5,
    "YEAST_MOLD": 2.0,
    "LACTIC": 2.0,
    "PEROXIDE_VALUE": 1.0,
    "PH": 0.5,
    "WATER_ACTIVITY": 0.5,
}

# --- Endpoint trip limits (PRD §3.6, inclusive at-or-above) ------------------
TRIP_LIMITS = {
    "APC": 6.0,
    "YEAST_MOLD": 5.0,
    "LACTIC": 7.0,
    "PEROXIDE_VALUE": 20.0,
    "PH": 8.0,
    "WATER_ACTIVITY": 0.95,
}

# --- Valid measurement ranges (PRD §3.6, inclusive) --------------------------
MEASUREMENT_RANGES = {
    "APC": (0.0, 12.0),
    "YEAST_MOLD": (0.0, 10.0),
    "LACTIC": (0.0, 10.0),
    "PEROXIDE_VALUE": (0.0, 500.0),
    "PH": (0.0, 14.0),
    "WATER_ACTIVITY": (0.0, 1.0),
}

# --- Date-code recommendation (PRD §3.7) -------------------------------------
SAFETY_FACTOR = 0.2
INCREMENT_SMALL = 7
INCREMENT_LARGE = 30
INCREMENT_TIER_BOUNDARY = 90

# --- Retain window (PRD §3.3) ------------------------------------------------
RETENTION_DAYS = 90

# --- Q10 defaults (PRD §3.2) -------------------------------------------------
DEFAULT_Q10 = 2.0
DEFAULT_REFERENCE_TEMP_C = 20

# --- Correlation read (PRD §3.6) ---------------------------------------------
MIN_CORRELATION_PAIRS = 3

ALL_ATTRIBUTES = [
    "APPEARANCE", "AROMA", "FLAVOR", "TEXTURE", "OFF_FLAVOR", "OVERALL",
]

TEST_DEFAULTS = {
    "TARGET_SHELF_LIFE_DAYS": 60,
    "SENSORY_FAIL_THRESHOLD": 6.0,
    "MIN_DETECTABLE_DIFFERENCE": 3.0,
    "STORAGE_TEMP_C": 20,
    "TOPUP_HOURS": 100,
    "CHAMBER_CAPACITY": 10,
    "PLANNED_START": "2026-08-01T00:00:00Z",
}
