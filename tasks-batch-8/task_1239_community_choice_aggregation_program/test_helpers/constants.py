"""Domain thresholds and shared test values (PRD §2.4, §2.6, §3)."""

# Logical-clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Convenience clock setting used by most enrollment setups: early enough that a
# notice mailed on the same day satisfies "not earlier than the current
# logical-clock date" (PRD §3.2).
CLOCK_BOOT = "2026-01-01T00:00:00Z"

# Calculation constants named in PRD prose
THRESHOLDS = {
    # "grossed up by a fifteen-percent planning reserve margin" (PRD §3.5)
    "RA_PLANNING_RESERVE_MARGIN": 0.15,
    # "converted from kWh to MWh at a thousand kWh per MWh" (PRD §3.5)
    "KWH_PER_MWH": 1000,
    # "the denominator is 10000" for basis-point quantities (PRD §2.6)
    "BPS_DENOMINATOR": 10000,
    # "a fixed termination charge of twenty percent" (PRD §3.5)
    "TERMINATION_FEE_PCT": 0.20,
}

TEST_DEFAULTS = {
    "ENERGY_RATE_CENTS_PER_KWH": 11.40,
    "PCIA_RATE_CENTS_PER_KWH": 1.50,
    "INCUMBENT_BENCHMARK_CENTS_PER_KWH": 12.00,
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2027-01-01T00:00:00Z",
    "PRODUCT_CODE": "STANDARD50",
    "RPS_TARGET_PCT": 0.60,
    "BAD_DEBT_TRUEUP_CAP_PCT": 0.01,
}
