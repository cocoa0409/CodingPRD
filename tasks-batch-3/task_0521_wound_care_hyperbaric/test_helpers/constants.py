"""Domain thresholds — numeric constants from PRD calculations."""

# Wound severity score (PRD §3.3)
STAGE_POINTS = {
    "STAGE_1": 1,
    "STAGE_2": 2,
    "STAGE_3": 4,
    "STAGE_4": 8,
    "UNSTAGEABLE": 10,
}
TISSUE_BONUS = {
    "GRANULATION": 0,
    "EPITHELIAL": -1,
    "SLOUGH": 2,
    "NECROTIC": 4,
}
INFECTION_BONUS = 5
AREA_TIER_LOW = 4     # area <= 4 -> 1.0x
AREA_TIER_HIGH = 16   # area <= 16 -> 1.5x, else 2.0x
SCORE_FLOOR = 1
SCORE_CEIL = 100

# Chamber defaults (PRD §3.1)
DEFAULT_TURNOVER_BUFFER_MINUTES = 30

# Payer policy defaults (PRD §3.1)
DEFAULT_MIN_HEALING_PCT_THRESHOLD = 50

# Test defaults
TEST_DEFAULTS = {
    "PER_SESSION_CENTS": 45000,
    "MAX_COVERED_HBO_SESSIONS": 4,
    "BUDGET_CENTS": 500000,
}
