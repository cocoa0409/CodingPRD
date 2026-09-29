"""Domain thresholds and pinned numeric constants stated by the PRD."""

# ---- logical clock ---------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ---- staffing capacity ----------------------------------------------------
BASE_CAPACITY_UNITS = {
    "CHARGE": 3.0,
    "BEDSIDE": 4.0,
    "ONE_TO_ONE_FLOAT": 4.0,
    "OR_STANDBY": 2.0,
    "TRIAGE": 6.0,
}
CERT_CAP_UNITS = {"ADVANCED": 4.0, "BASIC": 3.0, "EXPIRED": 0.0}
CHARGE_ADMIN_OFFSET_UNITS = 1.0
TIER_IV_FOCUS_PENALTY_UNITS = 1.0
MAX_SHIFT_MINUTES = 720

# ---- acuity ---------------------------------------------------------------
ACUITY_UNITS = {"TIER_I": 1.0, "TIER_II": 1.5, "TIER_III": 2.0, "TIER_IV": 4.0}
PHASE_MULTIPLIER = {
    "ANTEPARTUM": 0.5,
    "LATENT": 1.0,
    "ACTIVE_FIRST_STAGE": 1.5,
    "SECOND_STAGE": 2.0,
    "THIRD_STAGE_DELIVERED": 1.5,
    "POSTPARTUM_RECOVERY": 0.5,
    "DISCHARGED": 0.0,
    "TRANSFERRED_OUT": 0.0,
}
ONE_TO_ONE_REQUIRED_UNITS = 4.0

# ---- unit posture ---------------------------------------------------------
DIVERT_DEFICIT_UNITS = 8.0
FREEZE_DEFICIT_UNITS = 4.0
ESCALATION_BREACH_FREEZE = 2
BUNDLE_BREACH_FREEZE = 3
TURNOVER_BUFFER_OPEN_MINUTES = 45
TURNOVER_BUFFER_CONSTRAINED_MINUTES = 75

# ---- bundles --------------------------------------------------------------
ACTIVATION_QBL_ML = 1000
STAGE_2_QBL_ML = 1500
STAGE_3_QBL_ML = 2500
SEVERE_SYSTOLIC_MMHG = 160
SEVERE_DIASTOLIC_MMHG = 110
LATE_CREDIT = 0.5
MISSED_PENALTY_POINTS = 10.0
MISSED_GRACE_MINUTES = 5
HEMORRHAGE_TEMPLATE = [
    ("QBL_MEASURE", 1, 1, 10),
    ("UTEROTONIC_GIVEN", 2, 1, 15),
    ("TYPE_AND_SCREEN", 3, 2, 20),
    ("MTP_ACTIVATED", 4, 3, 10),
]
HYPERTENSION_TEMPLATE = [
    ("ANTIHYPERTENSIVE_GIVEN", 1, 1, 30),
    ("MAGNESIUM_LOADED", 2, 1, 60),
    ("REPEAT_BP", 3, 2, 15),
    ("OB_AT_BEDSIDE", 4, 2, 20),
]

# ---- fetal monitoring escalation -----------------------------------------
ESCALATION_DUE_MINUTES = {"CATEGORY_II": 20, "CATEGORY_III": 5}
TIER_ADVANCE_MINUTES = {"CATEGORY_II": 15, "CATEGORY_III": 5}
REASSESSMENT_WINDOW_MINUTES = 30

# ---- cesarean readiness ---------------------------------------------------
D2I_TARGET_MINUTES = {"CATEGORY_1_CRASH": 15, "CATEGORY_2_URGENT": 30}
DRILL_PASS_MINUTES = 30
ROLLING_EVENT_WINDOW = 3
READINESS_READY_CEILING = 30.00
READINESS_DEGRADED_CEILING = 45.00
DRILL_CURRENCY_DAYS = 90
DRILL_REVISION_LIMIT = 2

# ---- induction bookings ---------------------------------------------------
ELECTIVE_GA_WEEKS = 39
BUMP_ESCALATION_LIMIT = 2
HOLD_TTL_MINUTES = 120
ADMIT_EARLY_GRACE_MINUTES = 30
DEFAULT_EXPECTED_LABOR_MINUTES = 720
DEFAULT_MAX_DAILY_INDUCTION_BED_MINUTES = 2880

# ---- quality measures ----------------------------------------------------
RATE_DECIMALS = 4
COMPOSITE_DECIMALS = 2

# ---- newborn reviews -----------------------------------------------------
DEBRIEF_DUE_HOURS = 72
REWORK_EXTENSION_HOURS = 24
REWORK_LIMIT = 2

# ---- support person passes ----------------------------------------------
BASE_SUPPORT_BY_PHASE = {
    "ANTEPARTUM": 2,
    "LATENT": 2,
    "ACTIVE_FIRST_STAGE": 2,
    "SECOND_STAGE": 1,
    "THIRD_STAGE_DELIVERED": 1,
    "POSTPARTUM_RECOVERY": 2,
    "DISCHARGED": 0,
    "TRANSFERRED_OUT": 0,
}
MAX_ROOM_OCCUPANCY = 4
PASS_VALID_HOURS = 24
REENTRY_LIMIT = 3

# ---- pagination ---------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
