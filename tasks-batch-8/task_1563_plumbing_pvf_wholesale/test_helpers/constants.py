"""Domain thresholds — numeric constants named in the PRD (§2.9–§2.11, §3).

All monetary values are integer cents per the PRD's rounding discipline.
"""

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Account tier discount percents (PRD §3.6).
    "TIER_DISCOUNT_PCT": {"STANDARD": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 15},
    # Price floor margin over replacement cost (PRD §3.4/§3.6).
    "MIN_MARGIN_PCT": 5,
    # Volume discount ladder (PRD §3.6): (threshold_cents, pct).
    "VOLUME_TIER1_THRESHOLD_CENTS": 500000,
    "VOLUME_TIER1_PCT": 2,
    "VOLUME_TIER2_THRESHOLD_CENTS": 2000000,
    "VOLUME_TIER2_PCT": 5,
    # Freight (PRD §3.6).
    "FREIGHT_FREE_THRESHOLD_CENTS": 50000,
    "FLAT_FREIGHT_CENTS": 2500,
    # Restocking fee tiers and return window (PRD §3.10).
    "RESTOCK_FEE_TIER1_DAYS": 30,
    "RESTOCK_FEE_TIER1_PCT": 10,
    "RESTOCK_FEE_TIER2_DAYS": 90,
    "RESTOCK_FEE_TIER2_PCT": 25,
    "RETURN_WINDOW_DAYS": 90,
    # Credit hold hysteresis (PRD §2.9).
    "HOLD_RELEASE_RATIO_PCT": 80,
    "TERMS_DAYS": {"COD": 0, "NET_15": 15, "NET_30": 30},
    # Will-call bin turnaround buffer in hours (PRD §2.11).
    "WILL_CALL_BUFFER_HOURS": 2,
}

TEST_DEFAULTS = {
    "BRANCH_NAME": "Main",
    "BRANCH_CODE": "M1",
    "COMPANY_NAME": "GC Corp",
    "PRICING_TIER": "GOLD",
    "TERMS": "NET_30",
    "CREDIT_LIMIT_CENTS": 10000000,
    "SKU": "P1",
    "LIST_PRICE_CENTS": 10000,
    "COST_CENTS": 5000,
    "CUBES_PER_UNIT": 10,
    "MANUFACTURER": "Acme",
    "VALID_UNTIL": "2026-12-31T00:00:00Z",
    "SLOT_WINDOW_START": "2026-08-02T08:00:00Z",
    "SLOT_WINDOW_END": "2026-08-02T12:00:00Z",
}
