"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Footage-estimate tiered pricing (PRD §3.2).
FOOTAGE_PRICING = {
    "SEASONAL_BASE_CENTS": 15000,
    "PERMANENT_BASE_CENTS": 40000,
    "TIER1_RATE_CENTS": 300,   # first 100 feet
    "TIER2_RATE_CENTS": 250,   # feet 101..200
    "TIER3_RATE_CENTS": 200,   # feet beyond 200
    "ACCESSORY_UNIT_CENTS": 1200,
    "COMPLEXITY_MULT": {"SIMPLE": 1.00, "MODERATE": 1.15, "COMPLEX": 1.30},
}

# Early-bird contract pricing tiers (PRD §3.1).
EARLY_BIRD_PRICING = {
    "TIER_LO_CENTS": 50000,
    "TIER_HI_CENTS": 100000,
    "RATE_LO": 0.05,
    "RATE_HI": 0.10,
}

# Financing (PRD §3.7).
PREPAY_FEE_BPS = 200

# Default pagination (PRD §2.3).
DEFAULT_LIMIT = 10
