"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Loyalty tier thresholds (§3.8; inclusive lower bounds).
LOYALTY_THRESHOLDS = {
    "SILVER_THRESHOLD": 50000,
    "GOLD_THRESHOLD": 150000,
}

# Loyalty point per-tier multipliers (§3.8).
TIER_MULT = {
    "BRONZE": 1.0,
    "SILVER": 1.25,
    "GOLD": 1.5,
}

# Allocation tier caps (§3.3).
TIER_MAX = {
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
}

# Grading dispute limit (§3.5).
DISPUTE_LIMIT = 3

# Consignment default commission fraction (§3.7).
DEFAULT_COMMISSION_PCT = 0.30

# Logical clock server-startup default (§2.9).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"
