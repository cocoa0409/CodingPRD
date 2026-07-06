"""Domain thresholds and numeric constants from the Weatherization PRD.

Generic ``NON_EXISTENT_UUID`` comes from the framework, not from here.
"""

# --- WAP income eligibility (PRD 3.1) -------------------------------------
FPL_MULTIPLIER = 2
FPL_SIZE1_CENTS = 1_500_000
FPL_PER_PERSON_CENTS = 500_000

# --- Verified energy savings (PRD 3.8) -----------------------------------
SAVINGS_PER_CFM50_KWH = 1.5

# --- Blower-door reduction threshold (PRD 3.8) ---------------------------
MIN_REDUCTION_PCT = 0.20

# --- Utility rebate schedule (PRD 3.7) -----------------------------------
# Tier by R-value: TIER1 R<30 ; TIER2 30<=R<49 ; TIER3 R>=49.
# Insulation categories are tiered (cents/sqft); sealing categories are FLAT.
RATE_TABLE = {
    "ATTIC_INSULATION": {"TIER1": 50, "TIER2": 90, "TIER3": 130},
    "WALL_INSULATION": {"TIER1": 40, "TIER2": 70, "TIER3": 100},
    "CRAWL_INSULATION": {"TIER1": 30, "TIER2": 55, "TIER3": 80},
    "AIR_SEALING": {"FLAT": 25},
    "DUCT_SEALING": {"FLAT": 20},
}
MEASURE_CAP_CENTS = 200_000

# --- Federal 25C tax credit (PRD 3.6) ------------------------------------
CREDIT_RATE = 0.30
ANNUAL_CAP_CENTS = 120_000

# --- Crew scheduling (PRD 3.5) -------------------------------------------
BUFFER_DAYS = 2

# --- Pagination (PRD 2.3) ------------------------------------------------
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# Convenient shared defaults used by fixtures/factories.
TEST_DEFAULTS = {
    "REBATE_BUDGET_CAP_CENTS": 300_000,
    "DEFAULT_START_DATE": "2026-06-01T00:00:00Z",
    "DEFAULT_END_DATE": "2026-06-05T00:00:00Z",
}
