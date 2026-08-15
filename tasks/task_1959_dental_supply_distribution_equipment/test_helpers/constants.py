"""Domain thresholds and numeric constants from the PRD's calculation rules (§2.5, §3)."""

THRESHOLDS = {
    # Logical clock startup default (PRD §2.5)
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
    # Usage averaging (PRD §3.2)
    "USAGE_WINDOW_DAYS": 28,
    "SECONDS_PER_DAY": 86400,
    # Volume discount tiers (PRD §3.3)
    "VOLUME_TIER1_THRESHOLD_CENTS": 500_000,
    "VOLUME_TIER1_PCT": 0.10,
    "VOLUME_TIER2_THRESHOLD_CENTS": 200_000,
    "VOLUME_TIER2_PCT": 0.05,
    # Bundle discount (PRD §3.3)
    "ELITE_TIER_BONUS": 0.02,
    # Rebate tier multipliers (PRD §3.4)
    "REBATE_MULT_STANDARD": 1.0,
    "REBATE_MULT_PREMIER": 1.1,
    "REBATE_MULT_ELITE": 1.25,
    # Repair cost (PRD §3.7)
    "LABOR_RATE_CENTS_PER_MINUTE": 200,
    "DIAGNOSTIC_ESTIMATE_CENTS": 7500,
    # Trade-in valuation (PRD §3.6)
    "MONTHLY_DEPRECIATION_FACTOR": 0.98,
    "MARKET_VALUE_FLOOR_FRACTION": 0.10,
    "SCRAP_VALUE_WORKING": 25_000,
    "SCRAP_VALUE_NEEDS_REPAIR": 10_000,
    "SCRAP_VALUE_SCRAP": 4_000,
    # Temporal windows (PRD §3.3, §3.7)
    "STARTUP_WINDOW_DAYS": 90,
    "REOPEN_WINDOW_DAYS": 30,
}

TEST_DEFAULTS = {
    "REGION": "R1",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "EQUIPMENT_SALE_PRICE_CENTS": 900_000,
    "PART_UNIT_PRICE_CENTS": 15_000,
}
