"""Domain thresholds — numeric constants from PRD calculations."""

# Index bands (aircraft length in feet; lower bound inclusive)
BAND_B_MIN_FT = 90
BAND_C_MIN_FT = 126
BAND_D_MIN_FT = 159
BAND_E_MIN_FT = 200

# Aircraft qualifying threshold (inclusive)
QUALIFYING_MIN_DAILY_DEPARTURES = 5.0

# Equipment-supported index requirements
VEH_REQ = {"A": 1, "B": 2, "C": 2, "D": 3, "E": 3}
WATER_REQ = {"A": 100, "B": 1500, "C": 3000, "D": 4000, "E": 6000}
DRY_CHEM_WATER_EQUIV_GAL_PER_LB = 1.2
MAX_SUBSTITUTION_PCT = 0.5

# Staffing-supported index requirements
STAFF_REQ = {"A": 2, "B": 3, "C": 3, "D": 4, "E": 5}

# Training currency (calendar months, inclusive)
TRAINING_CURRENCY_MONTHS = 12

# Drill outcome thresholds (inclusive)
DRILL_FIRST_MAX_SECONDS = 180
DRILL_ALL_MAX_SECONDS = 240

# Alert-level minimum effective index
ALERT_INDEX_REQ = {"ALERT_1": "A", "ALERT_2": "B", "ALERT_3": "C"}

# Incident report window (days, inclusive)
REPORT_WINDOW_DAYS = 10

# Downgrade notification cure deadline (days)
CURE_DAYS = 30

# Agent-expense cost constants (integer cents)
WATER_COST_CENTS_PER_GAL = 137
DRY_CHEM_COST_CENTS_PER_LB = 89

# Narrative minimum length (characters)
NARRATIVE_MIN_CHARS = 200

# Logical-clock default before any set
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Index ordering: NONE < A < B < C < D < E
INDEX_ORDER = ["NONE", "A", "B", "C", "D", "E"]
