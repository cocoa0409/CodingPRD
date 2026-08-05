"""Domain thresholds and catalogue values stated in the PRD."""

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- intake completeness -----------------------------------------------------
INTAKE_SECTION_WEIGHTS = {
    "CHIEF_COMPLAINT_TIMELINE": 25,
    "SYSTEMS_REVIEW": 25,
    "DIET_LIFESTYLE": 15,
    "MEDICATIONS_SUPPLEMENTS": 25,
    "FAMILY_HISTORY": 10,
}
INTAKE_SECTION_VALIDITY_DAYS = 180
INTAKE_BOOKING_MIN_SCORE = 60
INTAKE_PROTOCOL_MIN_SCORE = 85

# --- membership tiers --------------------------------------------------------
MEMBERSHIP_CYCLE_DAYS = 30
MEMBERSHIP_TIERS = {
    "FOUNDATION": {
        "monthly_fee_cents": 9900,
        "included_visits": 2,
        "included_lab_credits": 1,
        "dispensary_discount_pct": 0.05,
        "includes_messaging": False,
    },
    "CORE": {
        "monthly_fee_cents": 19900,
        "included_visits": 4,
        "included_lab_credits": 2,
        "dispensary_discount_pct": 0.10,
        "includes_messaging": True,
    },
    "PREMIER": {
        "monthly_fee_cents": 34900,
        "included_visits": 8,
        "included_lab_credits": 4,
        "dispensary_discount_pct": 0.20,
        "includes_messaging": True,
    },
}

# --- visits ------------------------------------------------------------------
VISIT_FEE_IN_PERSON_CENTS = 22500
VISIT_FEE_TELEHEALTH_CENTS = 18000
EVISIT_FEE_CENTS = 9500
EXTENDED_VISIT_THRESHOLD_MINUTES = 45
EXTENDED_VISIT_BLOCK_MINUTES = 15
EXTENDED_VISIT_BLOCK_FEE_CENTS = 4500
TELEHEALTH_TURNAROUND_BUFFER_MINUTES = 10
ENCOUNTER_CANCEL_REFUND_WINDOW_HOURS = 24
LATE_CANCEL_NO_SHOW_FEE_CENTS = 7500

# --- messaging / e-visit -----------------------------------------------------
MESSAGE_SLA_HOURS = 48
EVISIT_PATIENT_MESSAGE_THRESHOLD = 4
EVISIT_CLINICAL_MINUTES_THRESHOLD = 15

# --- functional lab panel catalogue -----------------------------------------
LAB_PANELS = {
    "SERUM_METABOLIC": {
        "specimen_type": "SERUM",
        "fasting_required": True,
        "cycle_day_window": None,
        "washout_class": None,
        "washout_days": 0,
        "cash_price_cents": 24000,
        "lab_credit_cost": 1,
    },
    "DUTCH_HORMONE": {
        "specimen_type": "DRIED_URINE",
        "fasting_required": False,
        "cycle_day_window": (19, 22),
        "washout_class": "HORMONE_SUPPORT",
        "washout_days": 14,
        "cash_price_cents": 39000,
        "lab_credit_cost": 2,
    },
    "SALIVA_CORTISOL": {
        "specimen_type": "SALIVA",
        "fasting_required": False,
        "cycle_day_window": None,
        "washout_class": "ADAPTOGEN",
        "washout_days": 7,
        "cash_price_cents": 21000,
        "lab_credit_cost": 1,
    },
    "STOOL_GI_MAP": {
        "specimen_type": "STOOL",
        "fasting_required": False,
        "cycle_day_window": None,
        "washout_class": "PROBIOTIC",
        "washout_days": 10,
        "cash_price_cents": 45000,
        "lab_credit_cost": 2,
    },
}

# --- referral ----------------------------------------------------------------
RED_FLAG_REFERRAL_DUE_DAYS = 3
REFERRAL_MAX_ATTEMPTS = 3

# --- dispensary --------------------------------------------------------------
REVERSAL_AUTHORIZATION_THRESHOLD_CENTS = 20000
ADVERSE_REVERSAL_WINDOW_DAYS = 14

# --- titration ---------------------------------------------------------------
SYMPTOM_SCALE_MAX = 40
TITRATION_ADVANCE_DELTA_MIN = 8
TITRATION_HOLD_DELTA_MIN = 3
TITRATION_REDUCE_DELTA_MIN = 0
TITRATION_DOSE_ADVANCE_MULTIPLIER = 1.25
TITRATION_DOSE_REDUCE_MULTIPLIER = 0.50

# --- superbill ---------------------------------------------------------------
SUPERBILL_MAX_REVISIONS = 3

# --- convenience test defaults ----------------------------------------------
TEST_DEFAULTS = {
    "STATE_CODE": "OR",
    "PRODUCT_RETAIL_CENTS": 4995,
    "PRODUCT_COST_CENTS": 3000,
    "LOT_QUANTITY": 20,
    "LOT_EXPIRY": "2026-12-31",
    "SYMPTOM_BASELINE": 28,
}

# A well-formed UUID that never resolves to a live row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-4000-8000-0000000000ff"
