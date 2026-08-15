"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Pacing tier selection (PRD §3.4)
    "MID_TIER_FLOOR_PCT": 50,
    "HIGH_TIER_FLOOR_PCT": 80,
    # Invoice eligibility window (PRD §3.4)
    "INVOICE_LOOKBACK_DAYS": 90,
    # Fraud screen (PRD §3.4)
    "SAME_SERVICE_ADDRESS_WEIGHT": 40,
    "SAME_SERVICE_ADDRESS_WINDOW_DAYS": 30,
    "ALLY_BURST_WEIGHT": 25,
    "ALLY_BURST_COUNT": 5,
    "ALLY_BURST_WINDOW_DAYS": 7,
    "INVOICE_GAP_WEIGHT": 15,
    "INVOICE_GAP_WINDOW_DAYS": 7,
    "SUSPECT_THRESHOLD": 50,
    # Inspection sampling (PRD §3.4)
    "SAMPLE_EVERY_N": 5,
    "LARGE_CLAIM_KWH_THRESHOLD": 10000,
    # Trade-ally standing (PRD §3.2)
    "PREFERRED_FLOOR": 90,
    "STANDARD_FLOOR": 70,
}

TIER_FACTORS = {
    "STANDARD_TIER": 1.00,
    "MID_TIER": 0.80,
    "HIGH_TIER": 0.50,
}

# Logical clock anchors. The fixed startup default per PRD §2.4 is
# 2026-08-01T00:00:00Z; most tests drive the clock forward to TEST_CLOCK.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
TEST_CLOCK = "2026-08-13T00:00:00Z"
TEST_DATE = "2026-08-13"

TEST_DEFAULTS = {
    "BUDGET_CAP_CENTS": 20_000_000,
    "SAVINGS_GOAL_KWH": 500_000,
    "BASE_RATE_CENTS": 10_000,
    "DEEMED_KWH_PER_UNIT": 100,
    "INVOICE_DATE": "2026-08-01",
}
