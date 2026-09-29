"""Business constants drawn verbatim from the PRD.

Every literal here is quoted from PRD.md so that tests never re-derive a
threshold by hand.  Nothing in this module performs I/O.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# "the logical clock, which is `2026-08-01T00:00:00Z` until it is first set."
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_COORDINATOR = "AccreditationCoordinator"
ROLE_BODY_REVIEWER = "AccreditationBodyReviewer"
ROLE_FDA_INSPECTOR = "FdaInspector"
ROLE_QA_OFFICER = "QualityAssuranceOfficer"
ROLE_INTERPRETING_PHYSICIAN = "InterpretingPhysician"
ROLE_TECHNOLOGIST = "Technologist"
ROLE_MEDICAL_PHYSICIST = "MedicalPhysicist"

ALL_SEVEN_ROLES = (
    ROLE_COORDINATOR,
    ROLE_BODY_REVIEWER,
    ROLE_FDA_INSPECTOR,
    ROLE_QA_OFFICER,
    ROLE_INTERPRETING_PHYSICIAN,
    ROLE_TECHNOLOGIST,
    ROLE_MEDICAL_PHYSICIST,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

DENSITY_NOTICE_RULES = ("FEDERAL_ONLY", "STATE_DENSE_ONLY", "STATE_ENHANCED_ALL")
SUPPLEMENTAL_COVERAGE_MANDATES = (
    "NONE",
    "COVERAGE_WITH_COST_SHARING",
    "COVERAGE_NO_COST_SHARING",
)
ACCREDITATION_BODIES = ("ACR", "STATE_CERTIFIED")
MODALITIES = ("DM_2D", "DBT_3D")
UNIT_ACCREDITATION_STATUSES = (
    "PROVISIONAL",
    "ACCREDITED",
    "PROBATION",
    "REACCREDITATION_DUE",
    "SUSPENDED",
)
UNIT_OPERATIONAL_STATES = ("IN_SERVICE", "OUT_OF_SERVICE")
UNIT_SURVEY_COMPLIANCE = ("CURRENT", "OVERDUE", "FAILED")
PERSONNEL_ROLE_TYPES = ("INTERPRETING_PHYSICIAN", "TECHNOLOGIST", "MEDICAL_PHYSICIST")
QUALIFICATION_STATUSES = ("PROVISIONAL", "QUALIFIED", "LAPSED", "INACTIVE")
CE_STATUSES = ("COMPLIANT", "GRACE", "DEFICIENT")
CREDIT_TYPES = ("CATEGORY_1_CE", "READ_VOLUME")
SURVEY_TYPES = ("ANNUAL", "POST_REPAIR", "MOBILE")
SURVEY_STATUSES = ("DRAFT", "PASSED", "FAILED_ACTION_REQUIRED", "FAILED_FINAL")
FAILURE_CODES = ("DETECTOR", "AEC", "COLLIMATION", "COMPRESSION", "DISPLAY", "SOFTWARE")
FAILURE_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
FAILURE_STATUSES = ("OPEN", "REPAIR_VERIFIED")
SUBMISSION_STATUSES = (
    "SUBMITTED",
    "REVISION_REQUIRED",
    "PASSED",
    "DENIED_FINAL",
    "WITHDRAWN",
)
REVIEW_DECISIONS = ("PASS", "REVISION_REQUIRED")
INSPECTION_FINDING_LEVELS = ("NONE", "LEVEL_3", "LEVEL_2", "LEVEL_1")
INSPECTION_STATUSES = ("RECORDED", "CORRECTIVE_ACTION_REQUIRED", "CLOSED")
EXAM_TYPES = ("SCREENING", "DIAGNOSTIC")
REPORT_STATUSES = ("AWAITING_INTERPRETATION", "INTERPRETED_FINAL", "AMENDED", "DELAYED")
NOTIFICATION_STATUSES = ("NOT_REQUIRED", "PENDING", "GENERATED", "SENT", "COMPLETE")
FOLLOW_UP_STATUSES = (
    "NOT_REQUIRED",
    "PENDING",
    "COMPLETED",
    "LOST_TO_FOLLOW_UP",
    "PENDING_EXTERNAL",
)
DENSITY_CATEGORIES = ("A", "B", "C", "D")
REPEAT_REASON_CODES = ("POSITIONING", "MOTION", "EXPOSURE", "ARTIFACT", "EQUIPMENT_FAILURE")
LETTER_TYPES = ("LAY_SUMMARY", "COMBINED")
LETTER_STATUSES = ("QUEUED", "SENT", "DELIVERED_ASSUMED", "UNDELIVERABLE", "SUPERSEDED")
DISPATCH_CHANNELS = ("MAIL", "PORTAL")
DENSITY_STATEMENT_CODES = ("FDA_DENSE", "FDA_NOT_DENSE")
SUPPLEMENTAL_MODALITIES = ("ULTRASOUND", "MRI", "CEM")
ORDER_STATUSES = (
    "RECOMMENDED",
    "COVERAGE_DETERMINED",
    "SCHEDULED",
    "COMPLETED",
    "LOST_TO_FOLLOW_UP",
    "REFERRED_OUT",
)
COVERAGE_OUTCOMES = (
    "UNDETERMINED",
    "COVERED_NO_COST_SHARE",
    "COVERED_WITH_COST_SHARE",
    "PATIENT_RESPONSIBILITY",
    "DENIED",
)
COVERAGE_TIERS = ("TIER_1", "TIER_2", "TIER_3")
AUDIT_CYCLE_STATUSES = ("OPEN", "LOCKED", "AMENDED")
PPV_VARIANTS = ("PPV1_SCREENING", "PPV3_BIOPSY_ALL")
COMPLIANCE_POSTURES = ("COMPLIANT", "CONDITIONAL", "SUSPENDED")
PATHOLOGY_RESULTS = ("PENDING", "BENIGN", "MALIGNANT")

# ---------------------------------------------------------------------------
# State policy declared defaults
# ---------------------------------------------------------------------------

DEFAULT_REQUIRED_NOTICE_CODES: list = []
DEFAULT_WAIVER_THRESHOLD_CENTS = 0
DEFAULT_FOLLOWUP_GRACE_DAYS = 60
DEFAULT_REPORT_TURNAROUND_DAYS = 30
DEFAULT_URGENT_REPORT_TURNAROUND_DAYS = 7
DEFAULT_CE_GRACE_DAYS = 90
DEFAULT_SUPPLEMENTAL_CONCURRENT_CAPACITY = 2
DEFAULT_FOLLOWUP_WINDOW_DAYS = 365

# ---------------------------------------------------------------------------
# Accreditation cycle
# ---------------------------------------------------------------------------

# "each filing escrows an application fee of 250000 cents"
APPLICATION_FEE_CENTS = 250000
# "the unit's `reaccreditation_attempts_remaining`, which starts at 3"
MAX_REACCREDITATION_ATTEMPTS = 3
# "`accreditation_expires_on` is set to the logical clock plus 1095 days"
REACCREDITATION_TERM_DAYS = 1095
# "whose clock has reached `accreditation_expires_on` minus 180 days"
REACCREDITATION_LEAD_DAYS = 180
# "whose clock has passed `accreditation_expires_on` plus 30 days"
CERTIFICATE_GRACE_DAYS = 30
MIN_PACKET_EXAMS = 2

# ---------------------------------------------------------------------------
# Physicist surveys
# ---------------------------------------------------------------------------

# "the `phantom_score` is at least 6.0; the `mean_glandular_dose_mgy` is at most 3.00"
SURVEY_PHANTOM_SCORE_MIN = 6.0
SURVEY_DOSE_MAX_MGY = 3.00
SURVEY_PHANTOM_SCORE_RANGE = (0.0, 12.0)
SURVEY_DOSE_RANGE = (0.00, 10.00)
# "the span between them at most 396 days"
SURVEY_WINDOW_MAX_DAYS = 396
# "`remediation_attempts` is bounded at 2"
MAX_REMEDIATION_ATTEMPTS = 2
# "true exactly when the `severity` is `CRITICAL` or the `failure_code` is one of
#  `DETECTOR`, `AEC` or `COLLIMATION`"
POST_REPAIR_SURVEY_FAILURE_CODES = ("DETECTOR", "AEC", "COLLIMATION")

# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

LEVEL_1_CORRECTIVE_ACTION_DAYS = 15
LEVEL_2_CORRECTIVE_ACTION_DAYS = 30

# ---------------------------------------------------------------------------
# Personnel thresholds
# ---------------------------------------------------------------------------

# "An `INTERPRETING_PHYSICIAN` needs at least 60 initial training hours and at
#  least 240 initial read volume. A `TECHNOLOGIST` needs at least 40 hours and at
#  least 25. A `MEDICAL_PHYSICIST` needs at least 20 hours and at least 1."
INITIAL_HOURS_REQUIRED = {
    "INTERPRETING_PHYSICIAN": 60,
    "TECHNOLOGIST": 40,
    "MEDICAL_PHYSICIST": 20,
}
INITIAL_VOLUME_REQUIRED = {
    "INTERPRETING_PHYSICIAN": 240,
    "TECHNOLOGIST": 25,
    "MEDICAL_PHYSICIST": 1,
}
# "at least 15 category-1 hours inside the 36-month window"
CONTINUING_CE_HOURS_REQUIRED = 15
# "an `INTERPRETING_PHYSICIAN` must show at least 960 interpretations inside the
#  24-month window, a `TECHNOLOGIST` at least 200, and a `MEDICAL_PHYSICIST` at least 2."
CONTINUING_VOLUME_REQUIRED = {
    "INTERPRETING_PHYSICIAN": 960,
    "TECHNOLOGIST": 200,
    "MEDICAL_PHYSICIST": 2,
}
# "the window that begins 1095 days before the clock and ends at the clock"
CE_LOOKBACK_DAYS = 1095
# "the window that begins 730 days before the clock"
VOLUME_LOOKBACK_DAYS = 730

# ---------------------------------------------------------------------------
# Exam / notification
# ---------------------------------------------------------------------------

BIRADS_RANGE = (0, 6)
# "The exam counts as urgent when its `birads_assessment` is 0, 4 or 5."
URGENT_BIRADS = (0, 4, 5)
# "The exam counts as dense when its `density_category` is `C` or `D`"
DENSE_DENSITY_CATEGORIES = ("C", "D")
# "the lower of the policy's `lay_summary_max_reading_grade` and the federal
#  ceiling of grade 8"
FEDERAL_MAX_READING_GRADE = 8
# "the lower of the policy's `lay_summary_deadline_days` and the federal ceiling
#  of 30 days"
FEDERAL_MAX_DEADLINE_DAYS = 30
# "when the exam is urgent, that result is lowered again to at most 7 days"
URGENT_MAX_DEADLINE_DAYS = 7
# "any letter still in `SENT` whose `sent_at` is at least 14 days before the
#  logical clock"
DELIVERY_ASSUMED_DAYS = 14

FDA_LAY_SUMMARY_CODE = "FDA-LAY-SUMMARY"
FDA_DENSE_CODE = "FDA-DENSE"
FDA_NOT_DENSE_CODE = "FDA-NOT-DENSE"
FDA_URGENT_FINDING_CODE = "FDA-URGENT-FINDING"

# ---------------------------------------------------------------------------
# Repeat rates
# ---------------------------------------------------------------------------

# "`repeat_rate_flag` is true exactly when `image_based_repeat_rate_pct` is
#  non-null and strictly greater than 5.00 percent"
REPEAT_RATE_FLAG_THRESHOLD_PCT = 5.00

# ---------------------------------------------------------------------------
# Supplemental coverage
# ---------------------------------------------------------------------------

# "The fee schedule is 28500 cents for `ULTRASOUND`, 120000 cents for `MRI`, and
#  60000 cents for `CEM`."
FEE_SCHEDULE_CENTS = {"ULTRASOUND": 28500, "MRI": 120000, "CEM": 60000}
# "the facility's 3000-cent administration fee"
SUPPLEMENTAL_ADMIN_FEE_CENTS = 3000
# "an allowed amount of at most 31500 cents is `TIER_1`, an allowed amount above
#  that but at most 63000 cents is `TIER_2`, and anything above 63000 cents is `TIER_3`"
TIER_1_CEILING_CENTS = 31500
TIER_2_CEILING_CENTS = 63000
# "0.615 for `TIER_1`, 0.775 for `TIER_2`, 0.90 for `TIER_3`"
TIER_RATES = {"TIER_1": 0.615, "TIER_2": 0.775, "TIER_3": 0.90}
# "30 minutes for `ULTRASOUND`, 45 minutes for `MRI`, and 30 minutes for `CEM`"
APPOINTMENT_DURATION_MINUTES = {"ULTRASOUND": 30, "MRI": 45, "CEM": 30}
# "plus 15 minutes of room turnover"
ROOM_TURNOVER_MINUTES = 15

# ---------------------------------------------------------------------------
# Audit metrics
# ---------------------------------------------------------------------------

# "the benchmark band whose lower bound is 5.00 percent and upper bound is 12.00 percent"
RECALL_BAND_LOW_PCT = 5.00
RECALL_BAND_HIGH_PCT = 12.00
FOLLOWUP_WINDOW_DAYS_RANGE = (30, 730)

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# The nine fields returned by a compliance run.
COMPLIANCE_RUN_FIELDS = (
    "ran_at",
    "units_marked_reaccreditation_due",
    "units_survey_overdue",
    "exams_marked_delayed",
    "letters_marked_delivered",
    "orders_marked_lost",
    "personnel_moved_to_grace",
    "personnel_moved_to_deficient",
    "compliance_posture",
)

# The nine-field audit metrics preview shape.
AUDIT_METRIC_FIELDS = (
    "variant",
    "screening_exam_count",
    "recall_count",
    "biopsy_count",
    "cancer_count",
    "excluded_exam_count",
    "recall_rate_pct",
    "ppv_pct",
    "abnormal_interpretation_flag",
)
