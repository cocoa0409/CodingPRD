"""Domain thresholds and constants from the PRD calculation narratives (§3.3-§3.9)."""

# Condition multipliers for appraisal valuation (PRD §3.3).
CONDITION_MULT = {
    "POOR": 0.4,
    "GOOD": 0.7,
    "VERY_GOOD": 1.0,
    "FINE": 1.4,
    "AS_NEW": 1.8,
}
FIRST_EDITION_PREMIUM = 0.5
RETAIL_MARKUP = 1.6

# First-edition determination boundary (PRD §3.3).
FIRST_EDITION_MAX_PRINTING = 1

# Buyback auto-approval threshold (PRD §3.6).
AUTO_APPROVE_LIMIT_CENTS = 5000

# Shipping cost constants (PRD §3.9).
BASE_CENTS = {1: 500, 2: 800, 3: 1200, 4: 1800}
FREE_WEIGHT_GRAMS = 500
WEIGHT_STEP_GRAMS = 250
PER_STEP_CENTS = 150
CARRIAGE_FLOOR_CENTS = 500
CARRIAGE_CAP_CENTS = 6000
INSURANCE_RATE = 0.02
INSURANCE_MIN_CENTS = 200
INSURANCE_CAP_CENTS = 5000

# Packing-slot idle buffer, minutes (PRD §3.9).
PACK_BUFFER_MINUTES = 15

# Sale order default tax fraction (PRD §3.8).
DEFAULT_TAX_PCT = 0.08

# Patron default commission fraction (PRD §3.1).
DEFAULT_COMMISSION_PCT = 0.30
