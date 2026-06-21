"""Domain thresholds — numeric constants from the PRD calculations (§3.5-§3.8)."""

# PDMP weighted risk score (PRD §3.7)
PDMP = {
    "FILL_WEIGHT": 10,
    "PRESCRIBER_WEIGHT": 15,
    "REVIEW_THRESHOLD": 30,
    "BLOCK_THRESHOLD": 60,
    "LOOKBACK_DAYS": 90,
}

# DUR high-dose detection (PRD §3.5)
HIGH_DOSE_UNITS_PER_DAY = 4

# Refill-too-soon default threshold fraction (PRD §3.1 / §3.8)
DEFAULT_REFILL_THRESHOLD_PCT = 0.80

# Prescription expiry windows (PRD §3.3)
NON_CONTROLLED_EXPIRY_DAYS = 365
CONTROLLED_EXPIRY_DAYS = 180

# Will-call pickup window (PRD §3.9)
WILL_CALL_DAYS = 10

# Prior-auth validity window (PRD §3.6)
PA_EXPIRY_DAYS = 30

# Plan defaults (PRD §3.1)
DEFAULT_DISPENSING_FEE_CENTS = 100
DEFAULT_COPAY_MIN_CENTS = 0
