"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

# Logical clock default (PRD §2.5): the clock reads this instant before any call.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Canonical pool week used across scenarios: Monday 2026-07-27 covers
# 2026-07-27 .. 2026-08-02 inclusive (PRD §3.6), so the default clock's date
# (2026-08-01) falls inside it.
DEFAULT_WEEK_START = "2026-07-27"
NEXT_WEEK_START = "2026-08-03"

# Maturity evaluation (PRD §3.2)
MATURITY_VALIDITY_HOURS = 120
DEFAULT_SAMPLED_AT = "2026-07-31T10:00:00Z"
DEFAULT_SAMPLE_EXPIRES_AT = "2026-08-05T10:00:00Z"  # sampled_at + 120h
VARIETY_MINIMUMS = {
    "HAMLIN": {"min_ratio": 9.0, "min_brix": 8.5, "min_juice": 42.0},
    "VALENCIA": {"min_ratio": 9.0, "min_brix": 9.0, "min_juice": 45.0},
    "RED_GRAPEFRUIT": {"min_ratio": 7.0, "min_brix": 8.0, "min_juice": 38.0},
    "TANGERINE": {"min_ratio": 9.5, "min_brix": 9.0, "min_juice": 40.0},
}
# Measurement tuples that satisfy every variety minimum (for PASS fixtures).
PASSING_SAMPLE = {
    "HAMLIN": {"brix": 9.0, "acid_pct": 1.0, "juice_pct": 45.0},
    "VALENCIA": {"brix": 9.0, "acid_pct": 1.0, "juice_pct": 45.0},
    "RED_GRAPEFRUIT": {"brix": 8.5, "acid_pct": 1.0, "juice_pct": 40.0},
    "TANGERINE": {"brix": 9.6, "acid_pct": 1.0, "juice_pct": 42.0},
}

# Grade-equivalent conversion weights (PRD §3.5)
GE_WEIGHT_FANCY = 1.15
GE_WEIGHT_CHOICE = 1.0
GE_WEIGHT_STANDARD = 0.9
GE_WEIGHT_JUICE = 0.35

# Fresh eligibility gate (PRD §3.5)
FRESH_COLOR_MIN = 6
FRESH_DEFECT_MAX = 20

# Pool pricing (PRD §3.6)
FILL_ASSUMPTION = 0.8
TIER1_MAX = 10000
TIER2_MAX = 50000
TIER_RATES = {"low": 150, "mid": 140, "high": 125}

# Settlement waterfall (PRD §3.6)
CARETAKING_OFFSET_CAP_PCT = 0.5

# Advance cap (PRD §3.6)
ADVANCE_CAP_PCT = 0.60

# Caretaking billing (PRD §3.7)
CHEMICAL_MARKUP_PCT = 0.12
RATE_CENTS_PER_ACRE = {
    "SPRAY": {"SMALL": 4200, "MEDIUM": 3900, "LARGE": 3500},
    "FERTILIZE": {"SMALL": 3800, "MEDIUM": 3500, "LARGE": 3100},
    "PRUNE": {"SMALL": 5500, "MEDIUM": 5200, "LARGE": 4800},
    "MOW": {"SMALL": 1800, "MEDIUM": 1700, "LARGE": 1500},
}
TIER_SMALL_MAX_EXCLUSIVE = 40
TIER_MEDIUM_MAX_INCLUSIVE = 120

# Degreening room defaults (PRD §3.4)
DEFAULT_ROOM_MIN_HOURS = 12
DEFAULT_ROOM_MAX_HOURS = 72

# Export protocol (PRD §3.9)
COLD_TREATMENT_MIN_HOURS = 24
CERT_VALIDITY_DAYS = 14

# Varieties that must pass through degreening before sorting (PRD §3.3)
DEGREENING_REQUIRED_VARIETIES = {"RED_GRAPEFRUIT", "TANGERINE"}

TEST_DEFAULTS = {
    "CREW_CAPACITY": 400,
    "ROOM_CAPACITY": 100,
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-08-01T12:00:00Z",
    "COUNTY_CODE": "POLK",
}
