"""Domain thresholds — numeric constants from the PRD calculations and windows."""

# --- Logical clock ---
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
BASE_CLOCK_ISO = "2026-06-01T00:00:00Z"

# --- inquiry_priority_score (§3.2) ---
ACUITY_BY_CARE_LEVEL = {
    "INDEPENDENT_LIVING": 22,
    "ASSISTED_LIVING": 57,
    "MEMORY_CARE": 86,
    "SKILLED_NURSING": 100,
}
URGENCY_HORIZON_DAYS = 90
BUDGET_REFERENCE_CENTS = 600000
W_ACUITY = 0.45
W_URGENCY = 0.35
W_BUDGET = 0.20

# --- recommended_care_level (§3.4) ---
SKILLED_NURSING_ACUITY_FLOOR = 25
MEMORY_CARE_COGNITIVE_FLOOR = 8
INDEPENDENT_LIVING_ACUITY_CEILING = 8
ASSISTED_LIVING_ACUITY_CEILING = 17

# --- affordability_ceiling (§3.4) ---
BUDGET_STRETCH_FACTOR = 1.10

# --- match_fit_score (§3.6) ---
CARE_EXACT = 100
CARE_ADJACENT = 60
CARE_MISMATCH = 0
CARE_ORDER = {
    "INDEPENDENT_LIVING": 1,
    "ASSISTED_LIVING": 2,
    "MEMORY_CARE": 3,
    "SKILLED_NURSING": 4,
}
BUDGET_COMFORT_RATIO = 0.85
BUDGET_FALLOFF_SLOPE = 300

# --- advisor_load_index (§3.9) ---
PRIORITY_SCORE_MAX = 100

# --- referral_fee (§3.11) ---
CARE_PREMIUM_PCT = {
    "INDEPENDENT_LIVING": 0.00,
    "ASSISTED_LIVING": 0.05,
    "MEMORY_CARE": 0.12,
    "SKILLED_NURSING": 0.15,
}
TIER_MULTIPLIER = {"STANDARD": 1.00, "PREFERRED": 1.10, "PREMIER": 1.25}
MIN_FEE_CENTS = 150000
MAX_FEE_CENTS = 900000
PRORATION_BASIS_DAYS = 30

# --- va_benefit_estimate (§3.5) ---
UME_INCOME_THRESHOLD_PCT = 0.05
VA_MAX_MONTHLY_CENTS = {
    "VA_AID_ATTENDANCE_MARRIED": 276000,
    "VA_AID_ATTENDANCE_SINGLE": 233000,
    "VA_SURVIVOR_PENSION": 149800,
    "LTC_INSURANCE": 200000,
    "BRIDGE_LOAN": 120000,
}

# --- clawback_amount (§3.13) ---
CLAWBACK_FULL_DAYS = 30
CLAWBACK_PARTIAL_DAYS = 90

# --- satisfaction_composite_score (§3.14) ---
W_NPS = 0.40
W_CARE = 0.35
W_VALUE = 0.25

# --- Windows / temporal thresholds ---
RESIDENCY_CONFIRM_DAYS = 14
SURVEY_ELIGIBLE_DAYS = 30
TOUR_MIN_MINUTES = 30
TOUR_MAX_MINUTES = 180
TRAVEL_BUFFER_MINUTES = 45
MAX_DISPUTE_ROUNDS = 2

# --- Pagination ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# A well-formed dashed UUID that no created row will use.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# --- Canonical scenario numbers (pre-computed in the design indices) ---
# Standard Cedar Grove / Ann / Q1 profile at clock 2026-06-01:
STD_PRIORITY_SCORE = 70.59         # inquiry ASSISTED_LIVING, target 2026-06-20, budget 520000
STD_AFFORDABILITY_CEILING = 572000  # assessment budget 520000 * 1.10
STD_FIT_SCORE = 94.47              # match at rate 500000 / ceiling 572000
STD_ESTIMATED_FEE = 492500         # estimated variant, rate 500000, PREFERRED, ASSISTED_LIVING
STD_FINAL_FEE = 180583             # final variant, move-in 2026-06-20 (proration 11/30)
