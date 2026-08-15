"""Domain thresholds — numeric constants from the PRD business rules."""

# Logical clock fixed start (PRD Section 2.5)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Log deck degrade accrual (PRD Section 3.2)
DECK = {
    "FREE_DECK_DAYS": 14,
    "DEGRADE_PCT_PER_WEEK": 3,
    "MAX_DEGRADE_PCT": 15,
    "DECK_CAPACITY_MBF": 500,
}

# Species shrink fractions for estimated dry volume (PRD Section 3.5)
SHRINK_PCT = {
    "DOUGLAS_FIR": 0.06,
    "PONDEROSA_PINE": 0.07,
    "HEMLOCK_FIR": 0.08,
    "CEDAR": 0.05,
}

# Kiln moisture pass tolerance (PRD Section 3.4)
MOISTURE_TOLERANCE_PCT = 2.0

# Kiln chamber turnaround buffer in hours (PRD Section 3.4)
KILN_TURNAROUND_HOURS = 4

# Spot pricing length multipliers (PRD Section 3.7)
LENGTH_MULT = {
    "RL": 0.96,
    8: 0.95,
    10: 0.97,
    12: 1.00,
    16: 1.08,
}

# Spot pricing volume discount tiers (PRD Section 3.7)
VOLUME_TIER_1_MBF = 10
VOLUME_TIER_1_DISCOUNT = 0.02
VOLUME_TIER_2_MBF = 50
VOLUME_TIER_2_DISCOUNT = 0.05

# Common schedule window used by kiln fixtures (clock starts 2026-08-01)
KILN_WINDOW = {
    "START": "2026-08-02T00:00:00Z",
    "END": "2026-08-05T00:00:00Z",
}

DEFAULT_TARGET_MOISTURE_PCT = 15.0
