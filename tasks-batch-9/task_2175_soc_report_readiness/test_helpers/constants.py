"""Domain thresholds and default test values drawn from the PRD's numeric rules."""

# Severity point values feeding base_debt_points.
SEVERITY_POINTS = {"LOW": 1, "MODERATE": 3, "HIGH": 8, "CRITICAL": 20}

# Remediation debt tiering: the tier is chosen from the pre-surcharge base.
DEBT_TIERS = {
    "TIER_1_MAX_BASE": 10,
    "TIER_2_MAX_BASE": 25,
    "TIER_1_RATE": 0.00,
    "TIER_2_RATE": 0.15,
    "TIER_3_RATE": 0.30,
}

# Posture thresholds.
POSTURE_THRESHOLDS = {
    "FROZEN_DEBT_THRESHOLD": 26.00,
    "RESTRICTED_DEBT_THRESHOLD": 11.00,
    "FROZEN_EXCEPTION_THRESHOLD": 3,
    "RESTRICTED_EXCEPTION_THRESHOLD": 1,
}

# Sampling.
FREQUENCY_BASE = {
    "DAILY": 25,
    "WEEKLY": 15,
    "MONTHLY": 5,
    "QUARTERLY": 2,
    "ANNUAL": 1,
    "ADHOC": 8,
}
AUTOMATION_FACTOR = 0.4
RISK_BUMP = {"LOW": 0, "MODERATE": 2, "HIGH": 5}
SOC1_ADDENDUM = 1
ALLOWED_DEVIATION_RATE = 0.10

# Exception projection.
PRECISION_ALLOWANCE = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
PERVASIVE_THRESHOLD_PCT = 0.20

# Evidence calendar.
PERIOD_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 30, "QUARTERLY": 91, "ANNUAL": 365}
GRACE_DAYS = 5
MISSED_INEFFECTIVE_THRESHOLD = 2

# Bridge letters and subservice windows.
MAX_BRIDGE_DAYS = 120
SUBSERVICE_BUFFER_DAYS = 1

# Logical clock default before any set call.
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

# The canonical observation window used across the suite (90 whole days).
OBS_START = "2026-09-01T00:00:00.000Z"
OBS_END = "2026-11-30T00:00:00.000Z"
OBS_DAYS = 90

# A well-formed UUID that never names a stored row.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
