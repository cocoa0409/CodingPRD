"""Domain thresholds — numeric constants from PRD formulas (§2.7-§2.9, §3)."""

THRESHOLDS = {
    # Fuel surcharge tiers on diesel_index_cents (PRD §3.3)
    "FUEL_TIER_1_MIN": 300,
    "FUEL_TIER_1_RATE": 0.015,
    "FUEL_TIER_2_MIN": 400,
    "FUEL_TIER_2_RATE": 0.030,
    "FUEL_TIER_3_MIN": 500,
    "FUEL_TIER_3_RATE": 0.045,
    # Volume discount tiers on pre-discount subtotal_cents (PRD §3.5)
    "DISCOUNT_TIER_1_MIN": 200000,
    "DISCOUNT_TIER_1_RATE": 0.015,
    "DISCOUNT_TIER_2_MIN": 500000,
    "DISCOUNT_TIER_2_RATE": 0.025,
    # Driver commission tiers on net_sales_cents (PRD §3.7)
    "COMMISSION_TIER_1_MIN": 500000,
    "COMMISSION_TIER_1_RATE": 0.24,
    "COMMISSION_TIER_2_MIN": 1200000,
    "COMMISSION_TIER_2_RATE": 0.26,
    "COMMISSION_BASE_RATE": 0.22,
    "DRIVER_PER_MIN_CENTS": 50,
    # Territory valuation multiplier (PRD §3.8)
    "TERRITORY_MULTIPLIER": 10,
    # Cold-chain thresholds (PRD §2.9)
    "EXCURSION_THRESHOLD_TENTHS_F": 400,
    "CRITICAL_SPIKE_TENTHS_F": 500,
    "BREACH_THRESHOLD_MINUTES": 45.0,
    # Dock appointment buffer in minutes (PRD §3.4)
    "DOCK_BUFFER_MINUTES": 15,
    # Return credit percentages (PRD §3.6)
    "CREDIT_PCT_FULL": 1.0,
    "CREDIT_PCT_DAMAGED": 0.5,
}

# Documented defaults for optional create fields (PRD §3.1)
DEFAULTS = {
    "CREDIT_TERMS_DAYS": 7,
    "CREDIT_PRICE_BASIS": "ORIGINAL",
    "PULL_WINDOW_DAYS": 4,
    "CRATE_DEPOSIT_CENTS": 400,
    "MERCHANDISING_RATE_CENTS_PER_MIN": 0,
    "FREE_MERCHANDISING_MINUTES": 15,
    "DOCK_OPEN_MIN": 480,
    "DOCK_CLOSE_MIN": 720,
    "WEIGHT_LBS_PER_UNIT": 8.6,
    "LIST_PRICE_CENTS": 0,
    "MARGIN_CENTS_PER_UNIT": 0,
    "TRAILING_WEEKS": 12,
}

# Logical clock startup value (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common test values
TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100000000,
    "LIST_PRICE_CENTS": 250,
    "PRECOOL_TEMP_TENTHS_F": 380,
    "SERVICE_DATE": "2026-08-10",
    "PRICING_MONTH": "2026-08",
}
