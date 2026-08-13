"""Domain thresholds and numeric constants from the PRD (§2.5, §2.6, §3.3–§3.9)."""

# Logical clock (PRD §2.6): startup value of the server clock.
CLOCK_START = "2026-08-01T00:00:00Z"
DEFAULT_SCHEDULED_DATE = "2026-08-02"
DISPATCH_MORNING = "2026-08-02T08:00:00Z"

# Freight tier table (PRD §3.6) and dispatch-day fuel surcharge (PRD §3.7).
FREIGHT = {
    "TIER1_MAX_MILES": 25,
    "TIER1_FLAT_CENTS": 9500,
    "TIER2_MAX_MILES": 75,
    "TIER2_FLAT_CENTS": 19500,
    "TIER2_PER_MILE_CENTS": 320,
    "TIER3_PER_MILE_CENTS": 480,
    "FUEL_SURCHARGE_BP": 750,
}

# Waste allowance convention (PRD §2.5, §3.4).
WASTE = {
    "BP_DENOMINATOR": 10000,
    "MAX_WASTE_PCT_BP": 2000,
}

# Restocking fee rule (PRD §3.9).
RESTOCK = {
    "FREE_DAYS": 7,
    "FULL_BUNDLE_BP": 1500,
    "PARTIAL_BUNDLE_BP": 2500,
}

# Framing gates (PRD §3.3, §3.4).
FRAMING = {
    "MIN_FOR_STOCKING_OPEN": 50,
    "MIN_FOR_RATED_LINES": 30,
}

# Common test values derived from the PRD formulas above.
EXPECTED = {
    # round_half_up(9500 * (10000 + 750) / 10000) = round_half_up(10212.5)
    "FREIGHT_FINAL_TIER1_10MI": 10213,
    "FREIGHT_PROVISIONAL_10MI": 9500,
}
