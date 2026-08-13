"""Domain thresholds — numeric constants from PRD §2.5, §2.9 and §3."""

THRESHOLDS = {
    # Investment caps (PRD §2.9, §3.2)
    "BASE_CAP_PCT": 0.01,
    "EXTENDED_CAP_PCT": 0.03,
    "WELL_CAPITALIZED_MIN_RATIO": 0.07,
    # Concentration cap default (PRD §3.1)
    "DEFAULT_CONCENTRATION_CAP_PCT": 0.25,
    # Late penalty (PRD §2.9, §3.5)
    "LATE_PENALTY_DAILY_BPS": 3,
    # Day-count year (PRD §2.5)
    "YEAR_DAYS": 360,
    # Agreement policy defaults (PRD §3.3)
    "DEFAULT_GRACE_PERIOD_DAYS": 0,
    "DEFAULT_CURE_PERIOD_DAYS": 30,
    "DEFAULT_LATE_REMITTANCE_THRESHOLD": 2,
}

TEST_DEFAULTS = {
    "COMMIT_AMOUNT": 10_000_000,
    "POOL_PRINCIPAL": 100_000_000,
    "YIELD_BPS": 600,
    "SERVICING_FEE_BPS": 25,
    "REMITTANCE_DUE_DAY": 15,
}

# Logical clock startup value (PRD §2.4)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
