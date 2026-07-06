"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""

# Production throughput, sqft per hour (PRD §3.3).
PRODUCTION_RATE = {
    "LIGHT": 4000,
    "MEDIUM": 3000,
    "HEAVY": 2000,
}

# Supply rate, cents per square foot (PRD §3.4).
SUPPLY_RATE_CENTS_PER_SQFT = {
    "LIGHT": 1.0,
    "MEDIUM": 1.5,
    "HEAVY": 3.0,
}

WEEKS_PER_MONTH = 4.33

# Burden tiers on monthly_labor_hours (PRD §3.4).
BURDEN_T1 = 1.20
BURDEN_T2 = 1.28
BURDEN_T3 = 1.35
BURDEN_BREAK_1 = 160
BURDEN_BREAK_2 = 320

EQUIP_AMORT_CENTS = 7500
OVERHEAD_PCT = 0.15

# Proposal volume-discount tiers on base_bid_cents (PRD §3.5).
DISCOUNT_BREAK_1_CENTS = 500000
DISCOUNT_BREAK_2_CENTS = 800000
DISCOUNT_T1_PCT = 0.03
DISCOUNT_T2_PCT = 0.05

# Margin floor at send: achieved_margin_pct * 100 must be >= 15.0 (PRD §3.5).
MIN_MARGIN_PCT = 15.0

# Renewal escalation (PRD §3.10).
CPI_PCT = 0.032
FLAT_INCREASE_CENTS = 15000

TEST_DEFAULTS = {
    "BASE_WAGE_CENTS": 1800,
    "TARGET_MARGIN_PCT": 0.20,
}
