"""Domain thresholds and fixed values stated in the PRD (§2.4, §3.4–§3.8)."""

# Logical clock startup default (PRD §2.4: "initialized for every team to
# exactly 2026-08-01T00:00:00Z").
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # RTP readiness gate (PRD §3.4)
    "BASE_MIN_DAYS_PER_STAGE": 2,
    "SEVERE_EXTRA_DAYS": 2,
    "CONCUSSION_EXTRA_DAYS": 1,
    "MIN_CONCUSSION_DAYS_PER_STAGE": 3,
    "FUNCTIONAL_SCORE_MIN": 80,
    "REGRESSION_LOOKBACK_DAYS": 14,
    # Clearance (PRD §3.5)
    "CLEARANCE_TTL_HOURS": 72,
    "CLEARANCE_EVAL_MAX_AGE_HOURS": 72,
    # Claims (PRD §3.8)
    "MAX_APPEALS": 3,
    # Workload / ACWR (PRD §3.6)
    "ACWR_MIN_SESSIONS": 8,
    "ELEVATED_THRESHOLD": 1.300,
    "SPIKE_THRESHOLD": 1.500,
    "EXPOSURE_MIN_MINUTES": 10,
    # Trends (PRD §3.10)
    "RATE_MULTIPLIER": 1000,
}
