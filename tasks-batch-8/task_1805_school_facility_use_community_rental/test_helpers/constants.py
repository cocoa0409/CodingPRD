"""Domain thresholds and numeric constants (PRD §2.4, §3.3, §3.6, §3.7, §3.8, §3.9)."""

THRESHOLDS = {
    # Pricing (PRD §3.6)
    "BLOCK_MINUTES": 30,                 # duration billed in whole 30-minute blocks
    "LONG_BOOKING_HOURS": 6,             # >= 6 billable hours earns the rebate
    "LONG_BOOKING_DISCOUNT_PCT": 0.10,   # 10% off base rental fee
    "MIN_SHIFT_HOURS": 2.0,              # staffing floor when 0 < hours < 2.0
    "AFTER_HOURS_PCT": 0.50,             # uplift on staffing base
    "WEEKEND_PCT": 0.25,                 # uplift on staffing base; composes additively
    "DISCOUNT_TIER1_FLOOR_CENTS": 50000,    # 5%
    "DISCOUNT_TIER1_PCT": 0.05,
    "DISCOUNT_TIER2_FLOOR_CENTS": 100000,   # 10%
    "DISCOUNT_TIER2_PCT": 0.10,
    "DISCOUNT_TIER3_FLOOR_CENTS": 200000,   # 15%
    "DISCOUNT_TIER3_PCT": 0.15,
    # Cancellation refund tiers (PRD §3.7)
    "FULL_REFUND_DAYS": 14,
    "PARTIAL_REFUND_DAYS": 7,
    "PROCESSING_FEE_CENTS": 2500,
    # Insurance headcount tiers (PRD §3.3)
    "INS_TIER1_HEADCOUNT": 100,
    "INS_TIER1_PER_OCCURRENCE_CENTS": 100000000,
    "INS_TIER1_AGGREGATE_CENTS": 200000000,
    "INS_TIER2_HEADCOUNT": 500,
    "INS_TIER2_PER_OCCURRENCE_CENTS": 200000000,
    "INS_TIER2_AGGREGATE_CENTS": 400000000,
    "INS_TIER3_PER_OCCURRENCE_CENTS": 500000000,
    "INS_TIER3_AGGREGATE_CENTS": 1000000000,
    # Windows and caps
    "MAX_REQUEST_DURATION_HOURS": 12,
    "MAX_SEASON_SPAN_DAYS": 120,
    "APPEAL_WINDOW_DAYS": 14,
    "ARREARS_SUSPENSION_DAYS": 30,
    "FORFEITURE_SUSPENSION_COUNT": 3,
    "REVISION_ROUND_CAP": 3,
}

TEST_DEFAULTS = {
    # Logical clock startup default (PRD §2.4)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # Standard NP-STD policy fixture values
    "NP_STD_HOURLY_RATE_CENTS": 5000,
    "NP_STD_CUSTODIAL_HOURLY_CENTS": 4000,
    "NP_STD_DEPOSIT_BASIS_POINTS": 2000,
    "NP_STD_DEPOSIT_FLOOR_CENTS": 10000,
    # FP-PRE policy fixture values
    "FP_PRE_HOURLY_RATE_CENTS": 15000,
    "FP_PRE_CUSTODIAL_HOURLY_CENTS": 6000,
    "FP_PRE_DEPOSIT_BASIS_POINTS": 3000,
    "FP_PRE_DEPOSIT_FLOOR_CENTS": 20000,
}
