"""Domain thresholds — numeric constants drawn from the PRD calculations (§3).

Money is in integer cents. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Order total / volume discount (PRD §3.7)
ORDER_TOTAL = {
    "TIER1_THRESHOLD": 5000,
    "TIER1_PCT": 0.05,
    "TIER2_THRESHOLD": 15000,
    "TIER2_PCT": 0.10,
    "FREE_SHIP_THRESHOLD": 10000,
    "FLAT_SHIP_CENTS": 599,
}

# School commission tiers (PRD §3.7)
COMMISSION = {
    "TIER1_THRESHOLD": 50000,
    "TIER1_PCT": 0.20,
    "TIER2_THRESHOLD": 150000,
    "TIER2_PCT": 0.25,
    "BASE_PCT": 0.15,
}

# Retouch cost (PRD §3.5)
RETOUCH = {
    "BASE_RETOUCH_FEE": 1500,
    "PER_ADJUSTMENT_FEE": 500,
    "COMP_PCT": 0.5,
}

# Match confidence scoring (PRD §3.3)
MATCH = {
    "W_NAME": 0.5,
    "W_GRADE": 0.2,
    "W_HOMEROOM": 0.3,
    "MATCH_AUTO_THRESHOLD": 80,
}

# Capture-slot scheduling (PRD §3.2)
SCHEDULING = {
    "PHOTOGRAPHER_BUFFER_MIN": 10,
}

# Logical clock startup default (PRD §2.10)
CLOCK_START = "2026-01-01T00:00:00Z"
