"""Global constants and enumerations.

Every value here traces to SCAFFOLD.yaml `global_constants` or to a verbatim
sentence in PRD.md.  Nothing is invented.
"""

# --- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# --- scheduling geometry ---------------------------------------------------
APPOINTMENT_SLOT_MINUTES = 30
PROVIDER_BUFFER_MINUTES = 0
MAX_RESCHEDULES_PER_APPOINTMENT = 2

# --- eligibility / enrollment ----------------------------------------------
RETRO_TERMINATION_GRACE_DAYS = 30

# --- visits ----------------------------------------------------------------
MAX_VISIT_AMENDMENTS = 3

# --- biometric / HRA banding ------------------------------------------------
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
SELF_ATTEST_UNVERIFIED_MULTIPLIER = "1.25"
SELF_ATTEST_MISSING_METRIC_POINTS = 1
TOBACCO_SELF_REPORT_POINTS = 3
RISK_BAND_LOW_MAX_POINTS = 3
RISK_BAND_MODERATE_MAX_POINTS = 7
OUTCOME_STANDARD_MAX_POINTS = 5

# --- reasonable alternative standard ---------------------------------------
MAX_RAS_REASSIGNMENTS = 1
RAS_COMPLETION_WINDOW_DAYS = 90

# --- incentives -------------------------------------------------------------
INCENTIVE_CAP_PCT_STANDARD = "0.30"
INCENTIVE_CAP_PCT_TOBACCO = "0.50"
OUTCOME_AWARD_CENTS = 60000
PARTICIPATORY_AWARD_CENTS = 15000
TOBACCO_CESSATION_AWARD_CENTS = 45000

# --- referral / navigation SLA ---------------------------------------------
SLA_EMERGENT_HOURS = 4
SLA_URGENT_HOURS = 48
SLA_ROUTINE_BUSINESS_DAYS = 10

# --- reporting --------------------------------------------------------------
MIN_CELL_SIZE = 6
MAX_RESTATEMENTS = 2
DIVERSION_RATE_PRIMARY_CARE = "0.62"
DIVERSION_RATE_OCC_HEALTH = "0.40"
DIVERSION_RATE_WELLNESS = "0.15"
BENCHMARK_COST_PRIMARY_CARE_CENTS = 18533
BENCHMARK_COST_OCC_HEALTH_CENTS = 24011
BENCHMARK_COST_WELLNESS_CENTS = 9007
ROI_RATIO_DECIMALS = 4

# --- roles ------------------------------------------------------------------
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_CLINIC_MANAGER = "ClinicManager"
ROLE_CLINICIAN = "Clinician"
ROLE_CARE_NAVIGATOR = "CareNavigator"
ROLE_EMPLOYER_BENEFITS_ADMIN = "EmployerBenefitsAdmin"
ROLE_PARTICIPANT = "Participant"
ROLE_PAYROLL_PROCESSOR = "PayrollProcessor"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_CLINIC_MANAGER,
    ROLE_CLINICIAN,
    ROLE_CARE_NAVIGATOR,
    ROLE_EMPLOYER_BENEFITS_ADMIN,
    ROLE_PARTICIPANT,
    ROLE_PAYROLL_PROCESSOR,
]

EMPLOYER_SIDE_ROLES = {ROLE_EMPLOYER_BENEFITS_ADMIN, ROLE_PAYROLL_PROCESSOR}
CLINIC_SIDE_ROLES = {ROLE_CLINICIAN, ROLE_CARE_NAVIGATOR, ROLE_CLINIC_MANAGER}

# --- enum member sets -------------------------------------------------------
# Rung 8 (PRD 2.6) names thirteen enum-typed fields.  `fitness_conclusion` is
# an enum-valued input on visit completion and amendment and is routed through
# the same rung; the catalogue rule adopted here is that EVERY enum-valued
# input on a write endpoint reports enum-membership failure as
# ERR_INVALID_ENUM, not only the thirteen the prose happens to list.
ENUMS = {
    "site_type": ["ON_SITE", "NEAR_SITE"],
    "fee_model": ["PER_VISIT", "FTE_HOUR"],
    "provider_function": ["CLINICIAN", "NAVIGATOR"],
    "coverage_role": ["PRIMARY_CARE", "OCC_HEALTH", "WELLNESS", "NAVIGATION"],
    "tier": ["EMPLOYEE", "SPOUSE", "DEPENDENT", "RETIREE"],
    "decision": ["GRANT", "REVOKE"],
    "visit_type": ["PRIMARY_CARE", "OCC_HEALTH", "WELLNESS"],
    "cancellation_reason": [
        "PARTICIPANT_REQUEST",
        "CLINIC_REQUEST",
        "NO_SHOW",
        "ENROLLMENT_TERMINATED",
    ],
    "fitness_conclusion": ["FIT_FOR_DUTY", "FIT_WITH_RESTRICTIONS", "NOT_FIT"],
    "source_type": ["CLINIC_MEASURED", "SELF_ATTESTED"],
    "steerage_tier": [
        "CENTER_OF_EXCELLENCE",
        "PREFERRED",
        "STANDARD",
        "OUT_OF_NETWORK",
    ],
    "urgency": ["EMERGENT", "URGENT", "ROUTINE"],
    "alternative_type": [
        "COACHING_PROGRAM",
        "EDUCATION_MODULE",
        "PHYSICIAN_ALTERNATIVE",
    ],
    "award_type": ["OUTCOME_BASED", "PARTICIPATORY", "TOBACCO_CESSATION"],
}

VISIT_TYPES = ENUMS["visit_type"]

CHARGEABLE_PARTY_BY_VISIT_TYPE = {
    "PRIMARY_CARE": "HEALTH_PLAN",
    "OCC_HEALTH": "EMPLOYER_DIRECT",
    "WELLNESS": "WELLNESS_BUDGET",
}

DIVERSION_RATE_BY_VISIT_TYPE = {
    "PRIMARY_CARE": DIVERSION_RATE_PRIMARY_CARE,
    "OCC_HEALTH": DIVERSION_RATE_OCC_HEALTH,
    "WELLNESS": DIVERSION_RATE_WELLNESS,
}

BENCHMARK_CENTS_BY_VISIT_TYPE = {
    "PRIMARY_CARE": BENCHMARK_COST_PRIMARY_CARE_CENTS,
    "OCC_HEALTH": BENCHMARK_COST_OCC_HEALTH_CENTS,
    "WELLNESS": BENCHMARK_COST_WELLNESS_CENTS,
}

AWARD_AMOUNT_BY_TYPE = {
    "OUTCOME_BASED": OUTCOME_AWARD_CENTS,
    "PARTICIPATORY": PARTICIPATORY_AWARD_CENTS,
    "TOBACCO_CESSATION": TOBACCO_CESSATION_AWARD_CENTS,
}

# Award status -> reporting-period money bucket (PRD 2.12).
AWARD_STATUS_BUCKET = {
    "PENDING": "incentive_pending_cents",
    "APPROVED": "incentive_pending_cents",
    "EXPORTED": "incentive_pending_cents",
    "PAID": "incentive_paid_cents",
    "REVERSED": "incentive_reversed_cents",
    "FORFEITED": "incentive_forfeited_cents",
}

# Award statuses that commit employer wellness budget / consume cap headroom.
AWARD_COMMITTING_STATUSES = {"PENDING", "APPROVED", "EXPORTED", "PAID"}

# Encounter states that count as a delivered visit.
DELIVERED_ENCOUNTER_STATES = {"COMPLETED", "AMENDED", "LOCKED"}

# Appointment statuses that hold site capacity / provider occupation.
OCCUPYING_APPOINTMENT_STATUSES = {"BOOKED", "CONSUMED", "NO_SHOW"}
