"""Literal constants drawn from the API contract.

Every value here is stated verbatim in the specification: the logical clock's
starting instant, the benchmark day counts, the enumerated value sets, the
scoring weights, and the compliance-posture thresholds.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# "Every run begins with the logical clock at exactly 2026-08-01T00:00:00Z."
CLOCK_START = "2026-08-01T00:00:00Z"

SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_PROGRAM_AUDITOR = "ProgramAuditor"
ROLE_FACILITY_ADMIN = "FacilityAdmin"
ROLE_FACILITY_SCREENER = "FacilityScreener"
ROLE_AUDIOLOGIST = "Audiologist"
ROLE_NAVIGATOR = "Navigator"
ROLE_EI_COORDINATOR = "EICoordinator"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_PROGRAM_AUDITOR,
    ROLE_FACILITY_ADMIN,
    ROLE_FACILITY_SCREENER,
    ROLE_AUDIOLOGIST,
    ROLE_NAVIGATOR,
    ROLE_EI_COORDINATOR,
]

# Roles whose X-User-ID must resolve to a domain row.
ENTITY_BACKED_ROLES = {
    ROLE_FACILITY_ADMIN: "Facility",
    ROLE_FACILITY_SCREENER: "Provider",
    ROLE_AUDIOLOGIST: "Provider",
    ROLE_NAVIGATOR: "Provider",
    ROLE_EI_COORDINATOR: "Provider",
}

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

FACILITY_TYPES = [
    "BIRTH_HOSPITAL",
    "BIRTHING_CENTER",
    "MIDWIFE_PRACTICE",
    "AUDIOLOGY_CLINIC",
    "EI_PROGRAM",
]

REGION_CODES = ["R1", "R2", "R3", "R4"]

PROVIDER_TYPES = ["SCREENER", "AUDIOLOGIST", "NAVIGATOR", "EI_COORDINATOR"]

CREDENTIAL_STATUSES = ["ACTIVE", "LAPSED", "SUSPENDED"]

LANGUAGES = ["EN", "ES", "ZH", "VI", "AR", "ASL", "OTHER"]

SLOT_TYPES = ["RESCREEN", "DIAGNOSTIC"]

BIRTH_SETTINGS = ["INPATIENT", "BIRTHING_CENTER", "OUT_OF_HOSPITAL", "HOME_BIRTH"]

CONSENT_STATUSES = ["PENDING", "GRANTED", "REFUSED"]

SCREENING_STATUSES = [
    "NOT_SCREENED",
    "PASSED",
    "REFERRED",
    "DIAGNOSTIC_IN_PROGRESS",
    "DIAGNOSED_LOSS",
    "DIAGNOSED_NO_LOSS",
    "LOST_TO_FOLLOW_UP",
]

INTERVENTION_STATUSES = [
    "NOT_APPLICABLE",
    "REFERRAL_DUE",
    "REFERRED",
    "ENROLLED",
    "DECLINED",
]

ENCOUNTER_TYPES = ["BIRTH_ADMISSION", "OUTPATIENT_RESCREEN", "HOME_VISIT", "SURVEILLANCE"]

SCREEN_METHODS = ["OAE", "AABR"]

EAR_RESULTS = ["PASS", "REFER", "NOT_TESTED"]

OVERALL_RESULTS = ["PASS", "REFER", "INCOMPLETE"]

EPISODE_TYPES = ["INITIAL_SCREEN", "RESCREEN", "DIAGNOSTIC"]

EPISODE_ACTIVE_STATUSES = ["PENDING_SCHEDULING", "SCHEDULED", "ESCALATED_DIAGNOSTIC"]

EPISODE_TERMINAL_STATUSES = [
    "RESOLVED_PASS",
    "RESOLVED_DIAGNOSED",
    "RESOLVED_NO_LOSS",
    "CLOSED_DECLINED",
    "SUPERSEDED",
]

CLOSURE_REASONS = [
    "RESCREEN_PASSED",
    "DIAGNOSIS_CONFIRMED",
    "DIAGNOSIS_NO_LOSS",
    "FAMILY_DECLINED",
    "MOVED_OUT_OF_STATE",
    "SUPERSEDED",
    "LOST_TO_FOLLOW_UP",
]

TASK_TYPES = [
    "OUTREACH_CALL",
    "INTERPRETER_SESSION",
    "HOME_VISIT",
    "EI_LINKAGE",
    "APPOINTMENT_NAVIGATION",
]

TASK_OUTCOMES = ["CONTACTED", "FAMILY_REENGAGED", "NO_CONTACT", "INTERPRETER_PROVIDED", "LINKED"]

EVALUATION_METHODS = ["DIAGNOSTIC_ABR", "ASSR", "BEHAVIORAL"]

EVALUATION_OUTCOMES = ["NO_LOSS", "UNILATERAL_LOSS", "BILATERAL_LOSS"]

RISK_FACTOR_CODES = [
    "CMV",
    "FAMILY_HISTORY",
    "CRANIOFACIAL_ANOMALY",
    "SYNDROME",
    "BACTERIAL_MENINGITIS",
    "ECMO",
    "HYPERBILIRUBINEMIA_EXCHANGE",
    "OTOTOXIC_MEDICATION",
    "NICU_5_PLUS_DAYS",
]

# Codes whose surveillance horizon is 180 days rather than 270.
RISK_CODES_180_DAY = ["CMV", "BACTERIAL_MENINGITIS", "ECMO"]

COMPLIANCE_STATUSES = ["COMPLIANT", "WATCH", "PROBATION", "SUSPENDED"]

TIMELINESS_STATUSES = ["PENDING", "ON_TIME", "LATE", "OVERDUE"]

PRIORITY_BANDS = ["LOW", "ELEVATED", "HIGH", "CRITICAL"]

# ---------------------------------------------------------------------------
# Benchmarks and scoring
# ---------------------------------------------------------------------------

SCREENING_BENCHMARK_DAYS = 30
DIAGNOSTIC_BENCHMARK_DAYS = 90
EI_BENCHMARK_DAYS = 180
GRACE_BAND_DAYS = 45

TERM_GESTATION_WEEKS = 40
CORRECTED_BASIS_GESTATION_CEILING = 35
CORRECTED_BASIS_NICU_DAYS_FLOOR = 5

WEIGHT_SCREENED_RATE = 0.50
WEIGHT_FOLLOWUP_RATE = 0.30
WEIGHT_REPORT_TIMELINESS = 0.20

# LTF risk score terms.
SETTING_RISK_POINTS = {
    "INPATIENT": 0,
    "BIRTHING_CENTER": 8,
    "OUT_OF_HOSPITAL": 12,
    "HOME_BIRTH": 15,
}
LANGUAGE_GAP_POINTS = 10
MISSED_APPOINTMENT_POINTS_EACH = 6
MISSED_APPOINTMENT_POINTS_CAP = 24
RISK_FACTOR_POINTS_EACH = 4
RISK_FACTOR_POINTS_CAP = 16
AGE_PRESSURE_WITHIN_TEN_DAYS = 12
AGE_PRESSURE_PAST_BENCHMARK = 20
ESCALATION_POINTS = 6
NAVIGATION_RELIEF_POINTS = -8

BAND_CRITICAL_FLOOR = 45
BAND_HIGH_FLOOR = 30
BAND_ELEVATED_FLOOR = 15

# Navigation cost model.
TASK_BASE_UNITS = 2
TASK_INTERPRETER_UNITS = 3
TASK_HOME_VISIT_UNITS = 4

DEFAULT_NAVIGATION_BUDGET_UNITS = 40

TRAVEL_BUFFER_SECONDS = 45 * 60
FAMILY_BURDEN_BUFFER_SECONDS = 86400
MAX_BOOKING_ATTEMPTS = 3

# Diagnostic threshold rule.
NORMAL_HEARING_THRESHOLD_DB = 25

# Compliance posture thresholds keyed on penalty_points_balance.
POSTURE_COMPLIANT_CEILING = 4
POSTURE_WATCH_CEILING = 9
POSTURE_PROBATION_CEILING = 17

PENALTY_TIER_NONE_CEILING = 4
PENALTY_TIER_QUARTER_CEILING = 9
