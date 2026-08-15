"""Domain thresholds — numeric constants from PRD sections 3.3-3.8."""

PRICING = {
    # Freight tier distance cutoffs (PRD 3.3 step six)
    "LOCAL_MAX_MILES": 150.00,
    "REGIONAL_MAX_MILES": 400.00,
    # Freight tier rates per billable MSF (PRD 3.3 step seven)
    "TIER_RATE_LOCAL": 18.00,
    "TIER_RATE_REGIONAL": 32.00,
    "TIER_RATE_NATIONAL": 47.00,
    # Color surcharge per ink color per MSF (PRD 3.3 step three)
    "COLOR_SURCHARGE_PER_MSF": 1.50,
    # Routing multiplier (PRD 3.3 step four)
    "DIE_CUT_ROUTING_MULT": 1.12,
    "SLOTTED_ROUTING_MULT": 1.00,
    # Volume discount tiers keyed on merchandise_total_dollars only (PRD 3.3)
    "DISCOUNT_TIER1_MIN_DOLLARS": 5000.00,
    "DISCOUNT_TIER1_PCT": 0.02,
    "DISCOUNT_TIER2_MIN_DOLLARS": 20000.00,
    "DISCOUNT_TIER2_PCT": 0.04,
}

THRESHOLDS = {
    # Run completion trim gate (PRD 3.4)
    "MAX_TRIM_WASTE_IN": 8.0,
    # Converting changeover gaps (PRD 3.5)
    "CHANGEOVER_SAME_INK_MINUTES": 15,
    "CHANGEOVER_DIFF_INK_MINUTES": 45,
    # Overrun band factors (PRD 3.5)
    "OVERRUN_LOW_FACTOR": 0.90,
    "OVERRUN_HIGH_FACTOR": 1.10,
    # Claim freight reimbursement cap (PRD 3.8)
    "FREIGHT_REIMB_CAP": 500.00,
    # BOARD_WARP filing floor (PRD 3.8)
    "MIN_WARP_PCT": 2.0,
}

TEST_DEFAULTS = {
    # Canonical customer: 120.0 miles -> LOCAL tier
    "CUSTOMER_NAME": "Acme Foods",
    "CUSTOMER_CITY": "Fresno",
    "CUSTOMER_MILES": 120.0,
    "CUSTOMER_CREDIT_LIMIT": 50000.00,
    # Canonical grade 32C
    "GRADE_CODE": "32C",
    "GRADE_LINER": "35/23/35",
    "GRADE_FLUTE": "C",
    "GRADE_ECT": 32,
    "GRADE_BURST": 200,
    "GRADE_BASIS_WEIGHT": 90.0,
    # Second grade 44BC
    "GRADE44_CODE": "44BC",
    "GRADE44_LINER": "42/26/42/26/42",
    "GRADE44_FLUTE": "BC",
    "GRADE44_ECT": 44,
    "GRADE44_BURST": 275,
    "GRADE44_BASIS_WEIGHT": 120.0,
    # Canonical shift window (08:00-16:00)
    "SHIFT_DATE": "2026-08-10",
    "SHIFT_START": 480,
    "SHIFT_END": 960,
    # Canonical quote
    "UNIT_PRICE": 60.00,
    "QUOTE_EXPIRES_ON": "2026-12-31",
    # Inventory program defaults (mirror factories.DEFAULTS)
    "REORDER_POINT": 100,
    "REPLENISHMENT_QTY": 500,
    # Release-order default ship date
    "SHIP_DATE": "2026-08-12",
    # Logical clock default (PRD 2.4)
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
}

# Claims operators used by segregation-of-duties scenarios
CLAIMS_USERS = {
    "FILER_ID": "cs-100",
    "ADJUDICATOR_ID": "adj-200",
}

# A well-formed but never-created UUID for 404 scenarios
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
