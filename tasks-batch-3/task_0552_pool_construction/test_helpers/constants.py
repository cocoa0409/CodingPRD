"""Domain thresholds — numeric constants drawn from the PRD calculation rules.

Generic NON_EXISTENT_UUID comes from the framework (re-exported in __init__).
"""

# Completion factors keyed on phase-gate status (PRD §3.7 draw eligibility).
COMPLETION_FACTORS = {
    "PENDING": 0.0,
    "IN_PROGRESS": 0.5,
    "INSPECTION_PENDING": 0.8,
    "PASSED": 1.0,
    "FAILED": 0.0,
}

# Retainage percentage withheld at funding (PRD §3.7).
RETAINAGE_PCT = 0.10

# Volume-discount schedule for change-order apply (PRD §3.6).
DISCOUNT_TIERS = {
    "TIER1_CEILING_CENTS": 500000,   # cumulative base < 500000 -> 0%
    "TIER2_CEILING_CENTS": 1500000,  # 500000 <= base < 1500000 -> 3%
    "TIER1_PCT": 0.00,
    "TIER2_PCT": 0.03,
    "TIER3_PCT": 0.05,               # base >= 1500000 -> 5%
}

# Reliability defaults (PRD §3.5).
DEFAULT_RELIABILITY = 100

# Curing buffer between a GUNITE crew end and a PLASTER crew start (PRD §3.5).
CURE_BUFFER_HOURS = 24

# Sequence indices per phase (PRD §3.3).
PHASE_SEQUENCE = {
    "EXCAVATION": 1,
    "STEEL": 2,
    "PLUMBING": 3,
    "GUNITE": 4,
    "PLASTER": 5,
}

# Server logical-clock default before any adjustment (PRD §2.9).
LOGICAL_CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Convenient reusable payload defaults.
TEST_DEFAULTS = {
    "CONTRACT_PRICE_CENTS": 500000,
    "POOL_GALLONS": 20000,
    "PHASE_BUDGET_CENTS": 100000,
    "OWNER_USER_ID": "owner-1",
}
