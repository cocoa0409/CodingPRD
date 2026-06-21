"""Domain thresholds — numeric constants from the PRD calculation narratives."""

# Adoption fee (PRD §3.7) — tiered pricing, integer cents.
BASE_FEE_CENTS = {
    "PUPPY_KITTEN": 25000,
    "ADULT": 15000,
    "SENIOR": 5000,
}
MICROCHIP_SURCHARGE_CENTS = 2500
PROMO_PCT = 0.20
PROMO_FLAT_CENTS = 3000
MIN_FEE_CENTS = 0

# Age-band thresholds (months).
PUPPY_KITTEN_MAX_EXCLUSIVE = 6   # age_months < 6 -> PUPPY_KITTEN
SENIOR_MIN_INCLUSIVE = 84        # age_months >= 84 -> SENIOR

# Board cost (PRD §3.4) — round-per-day then sum.
CARE_FEE_PCT = 0.075
HOURS_PER_DAY = 24
DEFAULT_DOG_DAILY_BOARD_CENTS = 1850
DEFAULT_CAT_DAILY_BOARD_CENTS = 1250

# Shelter defaults (PRD §3.1).
DEFAULT_STRAY_HOLD_DAYS = 5
DEFAULT_PROMO_ACTIVE = False
DEFAULT_COLLECTED_FEE_CENTS = 0

# Foster home defaults (PRD §3.1).
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_COOLDOWN_DAYS = 3

# Kennel defaults (PRD §3.1).
DEFAULT_KENNEL_CAPACITY = 1

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_MIN = 0
