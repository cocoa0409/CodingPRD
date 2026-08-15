"""Domain thresholds — numeric constants from PRD calculation contracts."""

THRESHOLDS = {
    # Sensory composite (PRD §3.2)
    "W_AROMA": 0.40,
    "W_BRISKNESS": 0.35,
    "W_APPEARANCE": 0.25,
    "GRADE_A_MIN": 85.0,
    "GRADE_B_MIN": 70.0,
    "GRADE_C_MIN": 55.0,
    # Residue verdict (PRD §3.2)
    "RESIDUE_LIMIT_PPM": 0.50,
    "HARD_FAIL_MULTIPLIER": 2.0,
    # Moisture (PRD §3.4/§3.5/§3.7)
    "TARGET_MOISTURE_PCT": 5.0,
    "RELEASE_MAX_MOISTURE_PCT": 7.0,
    # Cost (PRD §3.5)
    "WASTE_FACTOR": 0.02,
    # Shelf life (PRD §3.7)
    "BASE_SHELF_DAYS_TEA_BAG": 540,
    "BASE_SHELF_DAYS_LOOSE_PACK": 365,
    "HARVEST_CEILING_DAYS": 730,
    # Contract pricing (PRD §3.8)
    "TIER1_UNITS": 10000,
    "TIER2_UNITS": 50000,
    "TIER3_UNITS": 100000,
    "MIN_UNIT_PRICE_CENTS": 1,
    # Allocation dominance (PRD §3.4)
    "DOMINANCE_MIN_COMPONENT_KG": 25.0,
    "DOMINANCE_MAX_SHARE": 0.70,
    # Allergen changeover (PRD §3.7)
    "ALLERGEN_CHANGEOVER_MINUTES": 45,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
    "LOT_COST_PER_KG_CENTS": 900,
    "LOT_MOISTURE_PCT": 5.0,
    "PASS_PPM": 0.20,
}
