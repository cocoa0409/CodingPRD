"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Pump drift verdict threshold (PRD §3.4): INVALID iff drift strictly exceeds it.
DRIFT_LIMIT_PCT = 5.00

# Time-weighted average constants (PRD §3.5).
FULL_SHIFT_MIN = 420
SHIFT_BASIS_MIN = 480

# Censored substitution (PRD §3.6).
DETECTION_RATIO_MIN = 0.5
MIN_N_FOR_SQRT2 = 3

# Required-sample-count sizing (PRD §3.3).
MIN_SAMPLES = 3
FOLLOWUP_ADJUSTMENT = 3
VERIFICATION_FLAT = 3

# Re-sampling intervals in days, keyed by exposure class (PRD §3.6).
RESAMPLE_INTERVAL_DAYS = {
    "ABOVE_PEL": 30,
    "UNCERTAIN": 90,
    "BELOW_PEL_MONITOR": 180,
    "BELOW_ACTION": 360,
}

# Control implementation pulls the group due date to now + this many days (§3.7).
VERIFICATION_DUE_DAYS = 14

# Employee notification deadline in working days (PRD §3.9).
NOTIFICATION_WORKING_DAYS = 15

# 95th-percentile Student t factors by degrees of freedom (PRD §3.6).
T95 = {
    1: 6.314,
    2: 2.920,
    3: 2.353,
    4: 2.132,
    5: 2.015,
    6: 1.943,
    7: 1.895,
    8: 1.860,
    9: 1.833,
    10: 1.812,
}

# Reference-data defaults (PRD §3.1).
DEFAULT_RETENTION_YEARS = 30
DEFAULT_ACTION_FRACTION = 0.1

# Clearance / fit-test validity window in days (PRD §3.8).
QUALIFICATION_VALIDITY_DAYS = 365

# Logical clock startup value (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical campaign dates used across the generated pipelines.
PLAN_START_DATE = "2026-08-03"
PLAN_END_DATE = "2026-08-14"
BATCH_WINDOW_START = "2026-08-10"
BATCH_WINDOW_END = "2026-08-14"
LAB_CLOCK = "2026-08-10T00:00:00Z"
