"""Domain thresholds and literals stated by the PRD."""

# --- logical clock -----------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- programs ----------------------------------------------------------------
DEFAULT_TIMELINESS_STANDARD_DAYS = 180
MIN_TIMELINESS_STANDARD_DAYS = 30
SURVEY_CYCLE_YEARS = 3
MIN_DAYS_UNTIL_SURVEY = 60
INITIAL_FOLLOW_UP_RATE_PCT = 100.0
INITIAL_LOST_TO_FOLLOW_UP_PCT = 0.0
ACCREDIT_MIN_FOLLOW_UP_RATE_COC_PCT = 80.0

# --- registry posture --------------------------------------------------------
POSTURE_FROZEN_CRITICAL_DEFICIENCY_MIN = 1
POSTURE_FROZEN_OVERDUE_BACKLOG_MIN = 2
POSTURE_RESTRICTED_OPEN_BACKLOG_MIN = 4

# --- casefinding / class of case --------------------------------------------
REFERRAL_ANALYTIC_MAX_DAYS = 120

# --- timeliness bands --------------------------------------------------------
AT_RISK_DAYS_TO_DUE_MAX = 30

# --- abstractor capacity / productivity -------------------------------------
CAPACITY_CASES_PER_FTE = 10
PRODUCTIVITY_WINDOW_DAYS = 30
PRODUCTIVITY_WORKING_DAYS_PER_MONTH = 21

# --- completeness scoring ----------------------------------------------------
COMPLETENESS_BASE_SCORE = 100
COMPLETENESS_PENALTY_MISSING = 12
COMPLETENESS_PENALTY_UNKNOWN = 8
COMPLETENESS_PENALTY_CLINICAL_ON_CLASS_10 = 6
COMPLETENESS_SCORE_MIN = 0
COMPLETENESS_SCORE_MAX = 100
SUBMIT_QA_MIN_COMPLETENESS_SCORE = 85

# --- rework / resubmission caps ---------------------------------------------
REWORK_ROUND_CAP = 2
RESUBMISSION_ROUND_CAP = 2
ENTRY_REOPEN_CAP = 1

# --- audits ------------------------------------------------------------------
AUDITOR_WINDOW_CAPACITY = 2
AUDIT_WEIGHT_CRITICAL = 5
AUDIT_WEIGHT_MAJOR = 3
AUDIT_WEIGHT_MINOR = 1
AUDIT_PASS_MAX_WEIGHTED_ERROR_SCORE = 2
CRITICAL_FAIL_STREAK_SUSPENSION_THRESHOLD = 3

# --- follow-up standing ------------------------------------------------------
FOLLOW_UP_CURRENT_MAX_DAYS = 365
FOLLOW_UP_DELINQUENT_MAX_DAYS = 456
FOLLOW_UP_LOST_MIN_DAYS = 457
COC_COHORT_WINDOW_DAYS = 1826

# --- submissions / assessments (integer cents) ------------------------------
ASSESSMENT_CENTS_PER_LATE_CASE = 2500
ASSESSMENT_BATCH_COMPONENT_CENTS = 15000
RELIEF_TIER_HIGH_SUBTOTAL_CENTS = 100000
RELIEF_TIER_HIGH_RATE = 0.30
RELIEF_TIER_MID_SUBTOTAL_CENTS = 50000
RELIEF_TIER_MID_RATE = 0.20
RELIEF_TIER_LOW_SUBTOTAL_CENTS = 20000
RELIEF_TIER_LOW_RATE = 0.10
EDIT_FAILED_RESPONSE_DAYS = 15

# --- conference sessions -----------------------------------------------------
CHANGEOVER_BUFFER_MINUTES = 30
QUORUM_MIN_ATTENDANCE_MINUTES = 30
QUORUM_MIN_PROSPECTIVE_RATIO = 0.80
REQUIRED_SESSIONS_HIGH_VOLUME = 24
REQUIRED_SESSIONS_STANDARD = 12
HIGH_VOLUME_CASELOAD_THRESHOLD = 500
COORDINATOR_MIN_ATTENDANCE_RATE_PCT = 50.0
CONFERENCE_COMPLIANCE_WINDOW_MONTHS = 12

# --- deficiencies ------------------------------------------------------------
DEFICIENCY_RESPONSE_WINDOW_DAYS = {
    "CRITICAL": 30,
    "MAJOR": 45,
    "MINOR": 60,
}
DEFICIENCY_REJECTION_EXTENSION_DAYS = 15
DEFICIENCY_ESCALATION_CAP = 2
AUTO_CITED_MEASURE_STANDARD_CODE = "STD 7.3"

# --- rounding precision ------------------------------------------------------
PRECISION_ONE_DP = 1
PRECISION_TWO_DP = 2
PRECISION_THREE_DP = 3
