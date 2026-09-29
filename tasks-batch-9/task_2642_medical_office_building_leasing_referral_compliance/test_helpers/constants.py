"""Domain thresholds and reference figures stated in the PRD."""

# --- Logical clock ---------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_DATE = "2026-08-01"

# --- Fair market value ----------------------------------------------------
SUITE_CLASS_PREMIUM_PSF = {
    "STANDARD_EXAM": 0.00,
    "IMAGING": 6.50,
    "PROCEDURE": 4.25,
    "INFUSION": 3.00,
}
PUBLISHED_FLOOR_FACTOR = 0.80
PUBLISHED_CEILING_FACTOR = 1.15
APPRAISAL_FLOOR_FACTOR = 0.90
APPRAISAL_CEILING_FACTOR = 1.10
FMV_DEVIATION_THRESHOLD_PCT = 0.1500
APPRAISAL_VALIDITY_DAYS = 365

# --- Lease term -----------------------------------------------------------
MIN_TERM_MONTHS = 12
REVISION_ROUND_CAP = 2
HOLDOVER_MULTIPLIER = 1.50

# --- Suite term turnover buffer (days), keyed on suite_class --------------
SUITE_TURNOVER_BUFFER_DAYS = {
    "STANDARD_EXAM": 0,
    "IMAGING": 30,
    "PROCEDURE": 14,
    "INFUSION": 14,
}

# --- Tenant mix -----------------------------------------------------------
MIX_RESTRICTED_THRESHOLD = 0.7500
MIX_ANCHOR_CONCENTRATED_THRESHOLD = 0.6000

# --- Parking --------------------------------------------------------------
STAFF_STALL_MONTHLY_RATE = 50.00
PATIENT_STALL_MONTHLY_RATE = 0.00
DEFAULT_PATIENT_MIN_RESERVE_PCT = 0.60

# --- Monthly occupancy charge: parking waiver tiers -----------------------
WAIVER_TIER_LOW_MAX = 5000.00
WAIVER_TIER_MID_MAX = 12000.00
WAIVER_TIER_PCT_LOW = 0.00
WAIVER_TIER_PCT_MID = 0.25
WAIVER_TIER_PCT_HIGH = 0.50

# --- Delinquency and risk scoring ----------------------------------------
GRACE_PERIOD_DAYS = 10
AGING_TIER_WEIGHT_EARLY = 15      # days_past_due_at_flag <= 30
AGING_TIER_WEIGHT_MIDDLE = 30     # days_past_due_at_flag <= 60
AGING_TIER_WEIGHT_LATE = 50       # days_past_due_at_flag > 60
AGING_TIER_EARLY_MAX_DAYS = 30
AGING_TIER_MIDDLE_MAX_DAYS = 60
WRITE_OFF_TIER_WEIGHT = 40
ROLLING_SCORE_CAP = 100
COMPLIANCE_WATCH_THRESHOLD = 45
ROLLING_WINDOW_DAYS = 365

# --- Compliance cases -----------------------------------------------------
CASE_SEVERITY_HIGH_THRESHOLD = 90
CASE_SEVERITY_MEDIUM_THRESHOLD = 45
REMEDIATION_WINDOW_DAYS = 30
CASE_REOPEN_HIGH_SEVERITY_COUNT = 2

# --- Pagination -----------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- The reference building used across the suite -------------------------
# 100000 rentable sf, published rate 30.00 psf, CAM 9.60 psf, 400 stalls,
# 0.60 patient reserve. Its published FMV bands follow directly.
REFERENCE_BUILDING = {
    "total_rentable_sf": 100000,
    "market_base_rent_psf_annual": 30.00,
    "operating_expense_annual_psf": 9.60,
    "total_parking_stalls": 400,
    "patient_min_reserve_pct": 0.60,
}
PUBLISHED_BAND = {
    "STANDARD_EXAM": (24.00, 34.50),
    "IMAGING": (29.20, 41.98),
    "PROCEDURE": (27.40, 39.39),
    "INFUSION": (26.40, 37.95),
}

# --- Segregation-of-duties user identities --------------------------------
SUBMITTING_AGENT_USER_ID = "agent-001"
CERTIFYING_OFFICER_USER_ID = "compliance-001"
SECOND_OFFICER_USER_ID = "compliance-002"
SYSTEM_USER_ID = "system"
