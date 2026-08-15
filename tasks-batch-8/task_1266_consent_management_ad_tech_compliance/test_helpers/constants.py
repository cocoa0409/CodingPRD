"""Domain thresholds — numeric constants from the PRD calculation rules."""

# Logical clock startup default (PRD section 2.4).
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Scan scheduling cooldown buffer in minutes (scan window expanded both sides).
    "SCAN_COOLDOWN_MINUTES": 120,
    # Vendor risk scoring weights.
    "WEIGHT_HIGH": 50,
    "WEIGHT_MEDIUM": 25,
    "RISK_SCORE_CAP": 100,
    # Sweep penalty formula constants (integer cents).
    "PENALTY_HIGH_BASE_CENTS": 250000,
    "PENALTY_MEDIUM_BASE_CENTS": 77777,
    "PENALTY_DAILY_RATE": 0.05,
    "PENALTY_DAY_CAP": 30,
}

# Pagination envelope defaults (PRD section 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

TEST_DEFAULTS = {
    "MIN_CONSENT_AGE": 16,
    "RETENTION_DAYS": 30,
    "DEADLINE_DAYS": 30,
}
