"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3.4, §3.5, §3.7)."""

# Delinquency / interest (§3.4)
GRACE_DAYS = 30
PENALTY_PCT = 0.10
DAILY_INTEREST_RATE = 0.0005

# Dispute window (§3.5)
DISPUTE_WINDOW_DAYS = 45

# Ambassador shift buffer (§3.7)
SHIFT_BUFFER_MINUTES = 30

# Petition (§3.6)
DEFAULT_REQUIRED_THRESHOLD_PCT = 0.50
DEFAULT_RENEWAL_TERM_MONTHS = 60

# Per-parcel assessment clamp defaults (§3.1)
DEFAULT_MIN_ASSESSMENT_CENTS = 50000
DEFAULT_MAX_ASSESSMENT_CENTS = 10000000

# Use-class multipliers (§3.1)
USE_CLASS_MULTIPLIER = {
    "RETAIL": 1.25,
    "MIXED": 1.15,
    "OFFICE": 1.10,
    "COMMERCIAL": 1.00,
    "INDUSTRIAL": 0.90,
    "RESIDENTIAL_EXEMPT": 0,
    "NONPROFIT_EXEMPT": 0,
}

# Clock startup default (§2.8)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Baseline BID weights used across most fixtures (weighted_base 700 for the canonical parcel)
BASE_WEIGHT_VALUE = 0.0005
BASE_WEIGHT_FRONTAGE = 2.0
BASE_WEIGHT_SQFT = 0.01
