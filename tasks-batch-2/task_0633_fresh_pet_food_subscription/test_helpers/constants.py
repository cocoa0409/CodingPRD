"""Domain thresholds — numeric constants from the PRD calculation rules.

These mirror the constants the PRD pins for the daily-calorie, cycle-price, shipping,
coolant, and referral-credit calculations. Generic ``NON_EXISTENT_UUID`` comes from the
framework.
"""

# Default logical-clock instant the server boots to (PRD §2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# Daily calorie target (PRD §3.3).
RER_COEFF = {"DOG": 70.0, "CAT": 60.0}
NEUTER_MULT = 1.0
INTACT_MULT = 1.2
ACTIVITY_MULT = {"LOW": 1.0, "MODERATE": 1.2, "HIGH": 1.5}
STAGE_MULT = {"PUPPY_KITTEN": 1.6, "ADULT": 1.0, "SENIOR": 0.9}
GOAL_MULT = {"LOSE": 0.8, "MAINTAIN": 1.0, "GAIN": 1.15}

# Cycle price / volume discount (PRD §3.5).
VOLUME_TIERS = "below 4000 -> 0.00; [4000,8000) -> 0.05; >=8000 -> 0.10"

# Shipping fee (PRD §3.7).
SHIP_BASE_CENTS = 999
FREE_SHIP_THRESHOLD_CENTS = 8000

# Coolant packs (PRD §3.9).
COOLANT_GRAMS_PER_PACK = 4000
COOLANT_FREE_DAYS = 2
COOLANT_MIN = 1

# Transit constraints (PRD §3.9).
TRANSIT_DAYS_MIN = 1
TRANSIT_DAYS_MAX = 5

# Cadence constraint (PRD §3.5).
VALID_CADENCES = (14, 21, 28)

# Referral credit (PRD §3.8).
REFERRED_FLAT_CENTS = 2000
REFERRER_FLAT_CENTS = 1500
REFERRER_ANNUAL_CAP_CENTS = 9000

# Subscription lifecycle (PRD §3.5 / §3.7).
TRANSITION_CYCLES = 2
MAX_FAILED_CHARGES = 3

THRESHOLDS = {
    "FREE_SHIP_THRESHOLD_CENTS": FREE_SHIP_THRESHOLD_CENTS,
    "SHIP_BASE_CENTS": SHIP_BASE_CENTS,
    "COOLANT_GRAMS_PER_PACK": COOLANT_GRAMS_PER_PACK,
    "COOLANT_FREE_DAYS": COOLANT_FREE_DAYS,
    "COOLANT_MIN": COOLANT_MIN,
    "REFERRED_FLAT_CENTS": REFERRED_FLAT_CENTS,
    "REFERRER_FLAT_CENTS": REFERRER_FLAT_CENTS,
    "REFERRER_ANNUAL_CAP_CENTS": REFERRER_ANNUAL_CAP_CENTS,
    "TRANSITION_CYCLES": TRANSITION_CYCLES,
    "MAX_FAILED_CHARGES": MAX_FAILED_CHARGES,
}
