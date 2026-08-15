"""Domain thresholds and rates from the PRD's calculation rules (§3.4, §3.6, §3.7, §3.8)."""

# Per-diem tier rates in integer cents, keyed [tier][day_kind] (PRD §3.8).
TIER_RATE_CENTS = {
    "TIER_A": {"TRAVEL_DAY": 12000, "GAME_DAY": 15000, "OFF_DAY": 9000, "PARTIAL_DAY": 6000},
    "TIER_B": {"TRAVEL_DAY": 9000, "GAME_DAY": 11000, "OFF_DAY": 7000, "PARTIAL_DAY": 4500},
    "TIER_C": {"TRAVEL_DAY": 6500, "GAME_DAY": 8000, "OFF_DAY": 5000, "PARTIAL_DAY": 3250},
}
MEAL_DEDUCTION_CENTS = 2500          # per team-provided meal (PRD §3.8)
MEALS_PROVIDED_MAX = 3               # meals_provided_count cap (PRD §3.8)

# League rest floor (PRD §3.4).
BASE_REST_MINUTES = {"STANDARD": 600, "STRINGENT": 720}
DELAY_COMPOUND_MINUTES = {"STANDARD": 60, "STRINGENT": 90}
DELAY_COMPOUND_FREE_MINUTES = 60     # first hour of prior delay adds nothing

# Equipment weight chargeback tiers (PRD §3.7).
CHARGEBACK_TIER1_PCT = 85            # up to and including 85% of capacity: free
CHARGEBACK_TIER2_RATE_CENTS_PER_LB = 350
CHARGEBACK_TIER3_RATE_CENTS_PER_LB = 900

# Charter execution window (PRD §3.3).
CONTRACT_EXECUTION_MIN_DAYS = 30

# Default hotel attrition allowance (PRD §3.6).
DEFAULT_ATTRITION_ALLOWANCE_PCT = 10

# Logical clock startup value (PRD §2.8).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "TRAVEL_BUDGET_CENTS": 100000000,
    "SEASON_LABEL": "2026-27",
    "GAME_TIPOFF": "2027-03-01T00:00:00Z",
    "RETURN_ARRIVAL": "2027-03-02T08:00:00Z",
}
