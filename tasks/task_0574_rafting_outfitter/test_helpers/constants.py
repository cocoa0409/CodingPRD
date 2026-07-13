"""Domain thresholds — numeric constants from the PRD's pricing, safety, and gratuity rules."""

# Monetary / pricing constants (PRD §2.5, §3.2, §3.6)
PHOTO_FEE_CENTS = 4000
DEPOSIT_PCT = 0.25

# Group-discount tiers (PRD §3.2)
DISCOUNT_TIER1_MIN_PARTY = 4     # party >= 4  -> 0.10
DISCOUNT_TIER1_PCT = 0.10
DISCOUNT_TIER2_MIN_PARTY = 8     # party >= 8  -> 0.15
DISCOUNT_TIER2_PCT = 0.15

# Guardian / age (PRD §3.3)
GUARDIAN_AGE_THRESHOLD = 18

# Guide gratuity role weights (PRD §3.9)
WEIGHT_LEAD = 3
WEIGHT_SAFETY = 2
WEIGHT_SWEEP = 1

# Shuttle turnaround buffer (PRD §3.8)
SHUTTLE_BUFFER_MINUTES = 30

# Server logical clock startup default (PRD §2.10)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Test defaults for trip flow bands
TEST_DEFAULTS = {
    "BASE_RATE_CENTS": 12000,
    "MAX_CAPACITY": 12,
    "GUIDE_RATIO_MAX": 6,
    "SAFE_FLOW_MIN": 800,
    "SAFE_FLOW_MAX": 3000,
    "MARGINAL_FLOW_MAX": 4000,
}
