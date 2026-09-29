"""Domain thresholds and numeric constants stated by the PRD."""

# --------------------------------------------------------------------------- #
# The logical clock (PRD §2.4)
# --------------------------------------------------------------------------- #
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Preadmission screening / admission gate (PRD §3.2, §3.3)
# --------------------------------------------------------------------------- #
SCREENING_WINDOW_HOURS = 48
SCREENING_EXPIRY_HOURS = 48

# --------------------------------------------------------------------------- #
# Plan of care (PRD §3.5)
# --------------------------------------------------------------------------- #
POC_DEADLINE_HOURS = 96

# --------------------------------------------------------------------------- #
# Three-hour rule (PRD §3.6)
# --------------------------------------------------------------------------- #
QUALIFYING_DAY_MINUTES = 180
DAILY_3HR_QUALIFYING_DAYS_REQUIRED = 5
WEEKLY_15HR_MINUTES_REQUIRED = 900
DEFAULT_DAILY_THERAPY_CAP_MINUTES = 300
THERAPY_WEEK_LENGTH_DAYS = 7
CONCURRENT_DIVISOR = 2
GROUP_SIZE_MIN = 3
GROUP_SIZE_MAX = 6
PATIENT_REST_BUFFER_MINUTES = 10

# --------------------------------------------------------------------------- #
# Compliance posture and review (PRD §2.8, §3.9)
# --------------------------------------------------------------------------- #
DEFAULT_COMPLIANCE_THRESHOLD_PCT = 60.00
POSTURE_FREEZE_MARGIN_PCT = 20.00
POSTURE_MIN_COHORT = 2
PRESUMPTIVE_IMPAIRMENT_GROUP_CODES = ["0008", "0110", "0704", "1101"]
PRESUMPTIVE_ETIOLOGIC_DIAGNOSIS_CODES = ["I63.9", "S72.001A"]
PRESUMPTIVE_SECONDARY_COMORBIDITY_TIERS = ["TIER_1", "TIER_2"]

# --------------------------------------------------------------------------- #
# Quality reporting programme (PRD §3.9)
# --------------------------------------------------------------------------- #
DATA_COMPLETENESS_PASS_PCT = 95.00
QRP_PENALTY_PCT_WHEN_INCOMPLETE = 2.00
QRP_PENALTY_PCT_WHEN_COMPLETE = 0.00

# --------------------------------------------------------------------------- #
# Assessment instrument deadlines (PRD §3.9)
# --------------------------------------------------------------------------- #
ADMISSION_REFERENCE_DATE_OFFSET_DAYS = 3
ADMISSION_COMPLETION_DEADLINE_OFFSET_DAYS = 4
DISCHARGE_COMPLETION_DEADLINE_OFFSET_DAYS = 5
TRANSMISSION_DEADLINE_OFFSET_DAYS = 17
MISSED_SWEEP_OFFSET_DAYS = 30

# --------------------------------------------------------------------------- #
# Interrupted stays (PRD §3.4)
# --------------------------------------------------------------------------- #
INTERRUPTION_MAX_GAP_DAYS = 3

# --------------------------------------------------------------------------- #
# Stay pricing waterfall (PRD §3.8)
# --------------------------------------------------------------------------- #
CMG_TIER_BASE_CENTS = {
    "TIER_A": 1800000,
    "TIER_B": 2450000,
    "TIER_C": 3120000,
}

CMG_TIER_AVG_LOS_DAYS = {
    "TIER_A": 9,
    "TIER_B": 12,
    "TIER_C": 15,
}

COMORBIDITY_UPLIFT_FRACTION = {
    "NONE": 0.00,
    "TIER_3": 0.03,
    "TIER_2": 0.06,
    "TIER_1": 0.12,
}

CMG_TIER_BY_IMPAIRMENT_GROUP_CODE = {
    "0008": "TIER_B",
    "0110": "TIER_C",
    "0704": "TIER_A",
    "1101": "TIER_A",
}
CMG_TIER_FALLBACK = "TIER_A"

SHORT_STAY_MAX_LOS_DAYS = 3
SHORT_STAY_FACTOR = 0.35
TRANSFER_DESTINATIONS = ["SNF", "ACUTE_CARE", "LTCH", "ANOTHER_IRF"]
TRANSFER_PER_DIEM_DAY_BONUS = 0.5

# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------- #
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------------------------------- #
# Test data defaults
# --------------------------------------------------------------------------- #
TEST_DEFAULTS = {
    "FACILITY_NAME": "Cedar Ridge Rehabilitation Hospital",
    "CMS_CCN": "100001",
    "REVIEW_PERIOD_START": "2026-08-01",
    "REVIEW_PERIOD_END": "2026-08-31",
    "PATIENT_BIRTH_DATE": "1955-03-14",
    "IMPAIRMENT_GROUP_CODE": "0008",
    "ETIOLOGIC_DIAGNOSIS_CODE": "I63.9",
    "SETUP_CLOCK": "2026-08-03T08:00:00Z",
    "SCREENING_CONDUCTED_AT": "2026-08-03T08:00:00Z",
    "EXPECTED_ADMISSION_AT": "2026-08-04T12:00:00Z",
    "ADMITTED_AT": "2026-08-04T12:00:00Z",
    "WEEK_START_DATE": "2026-08-04",
    "TARGET_LOS_DAYS": 14,
    "WEEKLY_MINUTES_TARGET": 900,
}
