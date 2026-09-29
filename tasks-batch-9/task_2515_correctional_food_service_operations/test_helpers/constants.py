"""Domain constants and thresholds drawn from the PRD.

Every value here is stated literally somewhere in the PRD narrative; nothing is
inferred. Tests import these instead of repeating magic numbers.
"""

# --- Logical clock -----------------------------------------------------------
# "Before the first call the clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) ----------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --- Menu cycle nutrition / cost --------------------------------------------
MEALS_PER_DAY = 3
SATELLITE_MULTIPLIER_NONE = 1.00      # zero satellite sites
SATELLITE_MULTIPLIER_LOW = 1.02       # one or two satellite sites
SATELLITE_MULTIPLIER_HIGH = 1.05      # three or more satellite sites

# --- Diet order validity (PRD 3.3) ------------------------------------------
RELIGIOUS_VALIDITY_DAYS = 180
MEDICAL_VALIDITY_DAYS = 30
MAX_REVERIFICATIONS = 2

# --- Forecast (PRD 3.4) ------------------------------------------------------
BASE_TRAY_RATE = 0.94
SATELLITE_TRAY_UPLIFT = 1.03
WASTE_FLAT_TRAYS = 8
WASTE_TIER_LOW_MAX = 500
WASTE_TIER_MID_MAX = 2000
WASTE_RATE_MID = 0.02
WASTE_RATE_HIGH = 0.015

# --- Cook-chill / HACCP (PRD 3.5) -------------------------------------------
CHILL_DEADLINE_MINUTES = 360
BUFFERED_RELEASE_EXTRA_MINUTES = 30
COOK_END_MIN_F = 165.0
CHILL_INTERMEDIATE_MAX_F = 80.0
CHILL_INTERMEDIATE_MAX_MINUTES = 120
CHILL_FINAL_MAX_F = 40.0
CHILL_FINAL_MAX_MINUTES = 360
TRANSPORT_MAX_F = 41.0
REHEAT_MIN_F = 165.0
REHEAT_MAX_MINUTES_AFTER_ARRIVAL = 30

# --- Contraband / posture (PRD 2.9, 3.6) ------------------------------------
CONTRABAND_POSTURE_THRESHOLD = 2

# --- Service record (PRD 3.7) -----------------------------------------------
MISSED_MEAL_TOLERANCE_RATE = 0.02
SPECIAL_DIET_MISS_WEIGHT = 3
MISSED_MEAL_ESCALATION_THRESHOLD = 25

# --- Substitution equivalence bands (PRD 3.7) -------------------------------
KCAL_BAND_PCT = 10.00
PROTEIN_BAND_PCT = -5.00
SODIUM_BAND_MG = 200.00
PROTEIN_DENOMINATOR_FLOOR = 0.01

# --- Grievance SLA (PRD 3.8) ------------------------------------------------
EXPEDITED_SLA_DAYS = 5
STANDARD_SLA_DAYS = 10
EXPEDITED_CATEGORIES = ("RELIGIOUS_DIET_DENIAL", "DIET_NOT_HONORED")
GRIEVANCE_BREACH_ESCALATION_THRESHOLD = 3

# --- Contract ledger (PRD 3.9) ----------------------------------------------
SURCHARGE_RATE = 0.15
SLA_BREACH_CENTS = 25000
COST_RECOVERY_CREDIT_RATE = 0.20
MISSED_MEAL_SCORE_WEIGHT = 2.5
BREACH_SCORE_WEIGHT = 5.0
COST_OVERRUN_SCORE_WEIGHT = 0.1
CORRECTIVE_ACTION_SCORE_FLOOR = 70.0
PERFORMANCE_SCORE_MAX = 100.00
PERFORMANCE_SCORE_MIN = 0.00

# --- Sharps classes (PRD 3.6) -----------------------------------------------
SHARP_TOOL_CLASSES = ("SHARP_KNIFE", "MEAT_SAW", "SCISSORS")
NON_SHARP_TOOL_CLASS = "NON_SHARP"
