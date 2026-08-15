"""Domain thresholds and constants from the PRD (§2.5, §3.2, §3.5, §3.7, §3.8)."""

# Default logical clock reading before any clock-setting call (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Waitlist priority score constants (PRD §3.2).
BASE_POINTS = 100
WAIT_POINTS_PER_DAY = 1
TRANSFER_PRIORITY_BONUS = 30

# Late fee constants (PRD §3.5).
LATE_FEE_FLOOR_CENTS = 500
LATE_FEE_DAILY_PCT = 0.005
LATE_FEE_CAP_PCT = 0.25

# Annual escalation (PRD §3.5).
ANNIVERSARY_DAYS = 365

# Insurance minimum liability coverage (PRD §3.7).
MIN_LIABILITY_COVERAGE_CENTS = 100000000

# Abandoned aircraft storage daily rate snapshot (PRD §3.8).
ABANDONED_AIRCRAFT_DAILY_CENTS = 2500

# Fixed delinquency eviction threshold (PRD §3.8).
DELINQUENCY_EVICTION_THRESHOLD_DAYS = 30

# Common airport configuration used by fixtures unless overridden.
DEFAULT_AIRPORT_CONFIG = {
    "escalation_pct": 0.0,
    "escalation_policy": "ANNIVERSARY_SIMPLE",
    "offer_acceptance_window_hours": 72,
    "cure_window_days": 30,
    "late_fee_grace_days": 5,
}

# Default long-lived insurance window used at lease activation.
DEFAULT_INSURANCE_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"
DEFAULT_INSURANCE_EFFECTIVE_TO = "2030-01-01T00:00:00Z"
