"""Domain thresholds — numeric constants from the PRD's calculation rules
(§2.11 freight economics, §3.3 bid evaluation, §3.7 attic target, §3.9 draw fee,
§3.3 sample-round cap, §3.1 project defaults)."""

THRESHOLDS = {
    # Freight (PRD §2.11)
    "FCL_CUBE_THRESHOLD_M3": 67,
    "FCL_FLAT_FREIGHT_CENTS": 480000,
    "LTL_RATE_PER_M3_CENTS": 9000,
    # Bid evaluation (PRD §3.3)
    "LEAD_TIME_PENALTY_PER_DAY_CENTS": 25000,
    "SAMPLE_ROUND_MAX": 2,
    # Attic target (PRD §3.7)
    "CRITICAL_ATTIC_MULTIPLIER": 2,
    # Project defaults (PRD §3.1)
    "DEFAULT_CREW_CAPACITY_PER_FLOOR_DAY": 8,
    "DEFAULT_REQUIRED_LEAD_DAYS": 21,
    "DEFAULT_ATTIC_TARGET_PCT": 0.05,
    "DEFAULT_ATTIC_MIN_QTY": 0,
    "DEFAULT_ATTIC_MAX_QTY": 9999,
}

# Contingency draw fee tiers (PRD §3.9)
FEE_TIERS = {
    "TIER1_MAX_UTILIZATION": 0.80,
    "TIER1_RATE": 0.05,
    "TIER2_MAX_UTILIZATION": 0.95,
    "TIER2_RATE": 0.08,
    "TIER3_RATE": 0.12,
}

TEST_DEFAULTS = {
    "TOTAL_BUDGET_CENTS": 10_000_000,
    "UNALLOCATED_CONTINGENCY_CENTS": 0,
    "BUDGETED_CENTS": 8_000_000,
    "CATEGORY": "FURNITURE",
    "VENDOR_NAME": "VENDA",
    "CARRIER_NAME": "CARR",
}
