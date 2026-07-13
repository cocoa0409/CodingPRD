"""Domain thresholds — numeric constants from the PRD's calculations (PRD §3.4, §3.8)."""

# --- Income eligibility (PRD §3.4) -----------------------------------------
FPL_ANNUAL_CENTS = {
    1: 1_506_000, 2: 2_044_000, 3: 2_582_000, 4: 3_120_000,
    5: 3_658_000, 6: 4_196_000, 7: 4_734_000, 8: 5_272_000,
}
FPL_ADDL_PER_PERSON_CENTS = 538_000
ELIGIBILITY_FPL_PCT = 150.00

# --- Benefit tier + award (PRD §3.4) ---------------------------------------
TIER_BASE_CENTS = {"TIER_1": 81_500, "TIER_2": 61_000, "TIER_3": 40_500}
HEATING_FACTOR = {"ELECTRICITY": 1.0, "NATURAL_GAS": 1.1, "FUEL_OIL": 1.3, "PROPANE": 1.25}
VULNERABILITY_SUPPLEMENT_CENTS = 15_000
MAX_BENEFIT_CENTS = 150_000
MIN_BENEFIT_CENTS = 10_000

# --- Crisis benefit (PRD §3.8) ---------------------------------------------
CRISIS_RATE_CENTS = {"NO_HEAT": 50_000, "DISCONNECTION_NOTICE": 40_000, "OUT_OF_FUEL": 60_000}
CRISIS_DEADLINE_HOURS = 48

# --- Logical clock (PRD §2.4) ----------------------------------------------
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# --- Pagination (PRD §2.3) -------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
