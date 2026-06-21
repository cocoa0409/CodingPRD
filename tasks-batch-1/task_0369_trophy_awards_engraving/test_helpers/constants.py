"""Domain thresholds — numeric constants from the PRD pricing and fee calculations."""

# Volume discount tiers (per-line quantity breakpoints; lower edge inclusive).
VOLUME_TIERS = {
    "TIER1_MIN": 25,
    "TIER2_MIN": 50,
    "TIER3_MIN": 100,
    "TIER1_PCT": 0.05,
    "TIER2_PCT": 0.10,
    "TIER3_PCT": 0.15,
}

# Rush-tier threshold: strict at 3 business days.
RUSH_MAX_BD_EXCLUSIVE = 3

# Deposit: half of invoice total, rounded up (RUSH orders prepay in full).
DEPOSIT_PCT = 0.50

# Ship fee tiered constants (cents).
SHIP_FEE = {
    "BASE": 1200,
    "PER_KG": 300,
    "PER_KG_HEAVY": 500,
}

# A clock instant used across deterministic due-date / business-day tests.
CLOCK_MONDAY = "2026-06-15T00:00:00Z"
