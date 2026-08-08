"""Domain thresholds and literal values taken from the PRD narrative.

Every value here is stated somewhere in PRD.md; nothing is invented.
"""

# --- The logical clock (PRD 2.5) -------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- Scheduling geometry (PRD 3.4, 2.10) -----------------------------------
APPOINTMENT_SLOT_MINUTES = 30
MAX_RESCHEDULES_PER_APPOINTMENT = 2

# --- Eligibility / enrollment (PRD 3.3) ------------------------------------
RETRO_TERMINATION_GRACE_DAYS = 30

# --- Visits (PRD 3.5) ------------------------------------------------------
MAX_VISIT_AMENDMENTS = 3

# --- Health-risk banding (PRD 3.6) -----------------------------------------
BP_ELEVATED_SYSTOLIC_MIN = 120
BP_ELEVATED_SYSTOLIC_MAX = 129
BP_STAGE1_SYSTOLIC_MIN = 130
BP_STAGE1_SYSTOLIC_MAX = 139
BP_STAGE1_DIASTOLIC_MIN = 80
BP_STAGE1_DIASTOLIC_MAX = 89
BP_STAGE2_SYSTOLIC_MIN = 140
BP_STAGE2_DIASTOLIC_MIN = 90
BMI_OVERWEIGHT_MIN = 25.0
BMI_OBESE1_MIN = 30.0
BMI_OBESE2_MIN = 35.0
A1C_PREDIABETES_MIN = 5.7
A1C_DIABETES_MIN = 6.5
LDL_BORDERLINE_MIN = 100
LDL_HIGH_MIN = 160
COTININE_POSITIVE_MIN = 10.0
SELF_ATTEST_UNVERIFIED_MULTIPLIER = 1.25
SELF_ATTEST_MISSING_METRIC_POINTS = 1
TOBACCO_POINTS = 3
RISK_BAND_LOW_MAX_POINTS = 3
RISK_BAND_MODERATE_MAX_POINTS = 7
OUTCOME_STANDARD_MAX_POINTS = 5

# --- Reasonable alternative standard (PRD 3.6) -----------------------------
MAX_RAS_REASSIGNMENTS = 1
RAS_COMPLETION_WINDOW_DAYS = 90

# --- Incentives (PRD 3.8) --------------------------------------------------
INCENTIVE_CAP_PCT_STANDARD = 0.30
INCENTIVE_CAP_PCT_TOBACCO = 0.50
OUTCOME_AWARD_CENTS = 60000
PARTICIPATORY_AWARD_CENTS = 15000
TOBACCO_CESSATION_AWARD_CENTS = 45000

AWARD_AMOUNT_BY_TYPE = {
    "OUTCOME_BASED": OUTCOME_AWARD_CENTS,
    "PARTICIPATORY": PARTICIPATORY_AWARD_CENTS,
    "TOBACCO_CESSATION": TOBACCO_CESSATION_AWARD_CENTS,
}

# --- Referral navigation SLA (PRD 3.7) -------------------------------------
SLA_EMERGENT_HOURS = 4
SLA_URGENT_HOURS = 48
SLA_ROUTINE_BUSINESS_DAYS = 10

# --- Reporting (PRD 3.9) ---------------------------------------------------
MIN_CELL_SIZE = 6
MAX_RESTATEMENTS = 2
DIVERSION_RATE_PRIMARY_CARE = 0.62
DIVERSION_RATE_OCC_HEALTH = 0.40
DIVERSION_RATE_WELLNESS = 0.15
BENCHMARK_COST_PRIMARY_CARE_CENTS = 18533
BENCHMARK_COST_OCC_HEALTH_CENTS = 24011
BENCHMARK_COST_WELLNESS_CENTS = 9007
RATIO_DECIMALS = 4

# --- Role groupings (PRD 2.1) ----------------------------------------------
EMPLOYER_SIDE_ROLES = ("EmployerBenefitsAdmin", "PayrollProcessor")
CLINIC_SIDE_ROLES = ("Clinician", "CareNavigator", "ClinicManager")

# --- Confidentiality-walled read routes (PRD 2.7) --------------------------
WALLED_READ_PATHS = (
    "/visits",
    "/health-assessments",
    "/referrals",
    "/alternative-standards",
)

# --- Convenient defaults for test payloads ---------------------------------
TEST_DEFAULTS = {
    "ANNUAL_TOTAL_COST_OF_COVERAGE_CENTS": 1200000,
    "WELLNESS_BUDGET_CENTS": 250000,
    "OPEN_TIME_UTC": "08:00",
    "CLOSE_TIME_UTC": "17:00",
    "OPERATING_WEEKDAYS": [1, 2, 3, 4, 5],
    "DAILY_SLOT_CAPACITY": 4,
    "PER_VISIT_FEE_CENTS": 9500,
    "FTE_HOURLY_RATE_CENTS": 14000,
    "MINIMUM_GUARANTEE_CENTS": 100000,
    "QUOTA_VISITS_TOTAL": 10,
    "LICENSE_EXPIRY_DATE": "2027-12-31",
    "SETUP_CLOCK": "2026-06-01T00:00:00Z",
    "SERVICE_DAY": "2026-06-08",
    "SHIFT_START": "2026-06-08T08:00:00Z",
    "SHIFT_END": "2026-06-08T17:00:00Z",
}
