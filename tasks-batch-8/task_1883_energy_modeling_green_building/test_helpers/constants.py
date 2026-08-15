"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Certification fee formula (PRD §3.4):
# fee = min(PHASE_BASE + FEE_PER_1000_SQFT * ceil(sqft / 1000), FEE_CAP)
FEE = {
    "DESIGN_BASE_CENTS": 250000,
    "CONSTRUCTION_BASE_CENTS": 350000,
    "FEE_PER_1000_SQFT_CENTS": 5000,
    "FEE_CAP_CENTS": 2000000,
}

# Certification level thresholds, inclusive >= (PRD §3.5)
LEVEL_THRESHOLDS = {
    "CERTIFIED_MIN": 40,
    "SILVER_MIN": 50,
    "GOLD_MIN": 60,
    "PLATINUM_MIN": 80,
}

# PERFORMANCE-path minimum improvement gate at PROPOSED lock (PRD §3.3)
MIN_IMPROVEMENT_PCT = 5.00

# Model-linked credit bucket table (PRD §3.5): threshold -> points
ENERGY_CREDIT_BUCKETS = [(18, 10), (14, 8), (10, 6), (8, 4), (5, 2)]

# Performance report tolerance, inclusive (PRD §3.8)
GAP_TOLERANCE_PCT = 15.00

# Incentive stacking cap share of incremental construction cost (PRD §3.7)
INCENTIVE_CAP_PCT = 0.40

# Logical clock startup default (PRD §2.10)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Common schedule window for commissioning tasks
CX_WINDOW = {
    "START": "2026-09-01T09:00:00Z",
    "END": "2026-09-01T12:00:00Z",
}

TEST_DEFAULTS = {
    "GROSS_FLOOR_AREA_SQFT": 120000,
    "FEE_BUDGET_CENTS": 5000000,
    "BASELINE_COST_CENTS": 12000000,
    "PROPOSED_COST_CENTS": 11400000,
    "INCREMENTAL_CONSTRUCTION_COST_CENTS": 50000000,
}
