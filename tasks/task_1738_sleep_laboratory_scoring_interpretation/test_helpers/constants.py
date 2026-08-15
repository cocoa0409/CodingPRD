"""Domain thresholds and defaults — numeric constants from the PRD."""

# Logical clock startup default (PRD: "the logical clock reads exactly
# 2026-08-01T00:00:00Z" at startup); timestamps serialize with three
# fractional digits per the common-resource rule.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"

# Severity bands (interpretation): NORMAL < 5.0 <= MILD < 15.0 <= MODERATE
# < 30.0 <= SEVERE, boundaries inclusive on the higher band.
SEVERITY_MILD_MIN = 5.0
SEVERITY_MODERATE_MIN = 15.0
SEVERITY_SEVERE_MIN = 30.0

# Split-night eligibility gate.
SPLIT_MIN_DIAGNOSTIC_MINUTES = 120
SPLIT_AHI_AUTO_THRESHOLD = 40.0
SPLIT_AHI_OVERRIDE_THRESHOLD = 20.0
SPLIT_MIN_REMAINING_MINUTES = 180
OVERRIDE_REASON_MIN_LEN = 10

# Titration pressure recommendation.
PRESSURE_MIN = 4.0
PRESSURE_MAX = 20.0
LOW_BAND_MAX = 10.0
LEAK_THRESHOLD_LOW = 24.0
LEAK_THRESHOLD_HIGH = 36.0

# Inter-rater reliability program.
CONCORDANCE_DELTA_MAX = 2.0
CONCORDANCE_AGREEMENT_MIN = 85.0
ROLLING_WINDOW = 5
MIN_CASES_FOR_STATUS = 3
CONSISTENT_MIN = 90.0
WATCH_MIN = 80.0
REMEDIATION_CONSECUTIVE = 2

# Interpretation turnaround SLA.
ROUTINE_SLA_BUSINESS_HOURS = 48.0
STAT_SLA_CALENDAR_HOURS = 24.0

# DME adherence compliance.
MIN_USAGE_HOURS = 4.0
MIN_COMPLIANT_NIGHTS_PERCENT = 70.0

# Registry / intake bounds.
APPROVED_NIGHTS_MIN = 1
APPROVED_NIGHTS_MAX = 2
PATIENT_CAPACITY_MIN = 1
PATIENT_CAPACITY_MAX = 4
DEFAULT_PATIENT_CAPACITY = 2
MIN_TOTAL_RECORDING_TIME_MINUTES = 60
RETURN_REASON_MIN_LEN = 10

TEST_DEFAULTS = {
    "WINDOW_START": "2026-07-01",
    "WINDOW_END": "2026-09-30",
    "STUDY_DATE": "2026-08-01",  # matches the logical-clock startup date
    "ICD10": "G47.33",
    "PAYER": "Aetna",
}
