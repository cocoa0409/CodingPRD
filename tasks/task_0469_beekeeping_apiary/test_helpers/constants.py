"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Colony strength scoring (PRD §3.3, §3.5)
W_BROOD = 8
W_HONEY = 3
STRENGTH_MITE_PENALTY = 25
STRENGTH_QUEEN_BONUS = 10
MITE_TREATMENT_THRESHOLD = 3.0
CONTRACT_GRADE_MIN = 60
STRENGTH_SCORE_MIN = 0
STRENGTH_SCORE_MAX = 100
BROOD_GROWTH_PER_WEEK = 2
MAX_BROOD_FRAMES = 20

# Honey yield (PRD §3.7)
KG_PER_FRAME_ESTIMATE = 2.5
EXTRACTION_LOSS_PCT = 0.04  # final = gross * 0.96

# Pollination payout (PRD §3.6)
STRONG_MULT = 1.20
SUB_GRADE_MULT = 0.50
STRONG_BONUS_MIN = 80
SHORTFALL_PENALTY_CENTS = 5000
FULL_BONUS_CENTS = 10000

# Honey revenue (PRD §3.7)
TIER1_MIN = 100000
TIER1_DISCOUNT = 0.05
TIER2_MIN = 500000
TIER2_DISCOUNT = 0.10

# Treatment withdrawal days by product (PRD §3.4)
WITHDRAWAL_DAYS = {
    "APIVAR": 14,
    "FORMIC_PRO": 0,
    "OXALIC_ACID": 0,
}

# Default clock instants used across fixtures
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"
