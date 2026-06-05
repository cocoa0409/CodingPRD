"""Domain thresholds — numeric constants derived from PRD prose (PRD §2.9, §3.2–§3.7).

These come from the calculations section of the PRD: 12-month tenure threshold,
1250-hour threshold, 480-hour FMLA annual quota, per-state PFL quotas, 15-day
certification window, 30-day delinquency cliff, 84-day job-restoration window.
"""

# Eligibility thresholds (PRD §3.3)
TENURE_THRESHOLD_MONTHS = 12
HOURS_THRESHOLD = 1250
DAYS_PER_MONTH = 30

# FMLA quota (PRD §2.9, §3.2)
FMLA_ANNUAL_QUOTA_HOURS = 480
FMLA_ROLLING_DAYS = 365

# Job-restoration window (PRD §3.6)
JOB_RESTORATION_DAYS = 84  # 12 weeks

# Statutory notice window (PRD §2.10)
CERT_RESPONSE_WINDOW_DAYS = 15
ELIGIBILITY_RESPONSE_WINDOW_DAYS = 5

# Delinquency cliff (PRD §3.7)
DELINQUENCY_GRACE_DAYS = 30

# Recertification window (PRD §3.5)
RECERT_MIN_INTERVAL_DAYS = 30

# Reverse window (PRD §3.6)
REVERSE_INTERVAL_WINDOW_DAYS = 14

# PFL per-state quota in hours (PRD §3.6)
PFL_QUOTA_HOURS = {
    "CA": 320,
    "NY": 480,
    "NJ": 480,
    "MA": 480,
    "WA": 480,
    "CT": 480,
    "RI": 200,
    "CO": 480,
    "OR": 480,
    "FED": 0,
}

# PFL-enabled state set (PRD §3.1)
PFL_ENABLED_STATES = {"CA", "NY", "NJ", "MA", "WA", "CT", "RI", "CO", "OR"}

# Qualifying reasons that allow concurrent PFL (PRD §3.4)
CONCURRENT_PFL_REASONS = {
    "OWN_SERIOUS_HEALTH_CONDITION",
    "FAMILY_SERIOUS_HEALTH_CONDITION",
    "NEW_CHILD_BONDING",
}

# Rounding precision (PRD §2.9, §3.7)
LEAVE_FRACTION_DP = 4

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
