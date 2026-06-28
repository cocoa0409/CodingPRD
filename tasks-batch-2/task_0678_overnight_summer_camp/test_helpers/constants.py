"""Domain thresholds — numeric constants from PRD calculations."""

# Tuition tiering (PRD §3.5)
BASE_TUITION_CENTS = 400_000
EARLY_DISCOUNT_CENTS = 30_000      # >= 60 days before start
LATE_SURCHARGE_CENTS = 25_000      # < 14 days before start
MED_PER_MED_CENTS = 1_500          # per daily medication
EPIPEN_SUPPORT_CENTS = 5_000       # added when life-threatening allergy

# Early-tier list tuition with no medical support (>= 60 days before start)
EARLY_TIER_CENTS = BASE_TUITION_CENTS - EARLY_DISCOUNT_CENTS   # 370_000
# Base-tier list tuition (14 <= days < 60)
BASE_TIER_CENTS = BASE_TUITION_CENTS                           # 400_000
# Late-tier list tuition (< 14 days before start)
LATE_TIER_CENTS = BASE_TUITION_CENTS + LATE_SURCHARGE_CENTS    # 425_000

# Camp config defaults (PRD §3.1)
DEFAULT_COUNSELOR_CAMPER_RATIO = 6
DEFAULT_CIT_COUNTS_AS_HALF = True
DEFAULT_DEPOSIT_CENTS = 25_000
DEFAULT_DEPOSIT_GRACE_DAYS = 7
DEFAULT_CANTEEN_LOW_BALANCE_CENTS = 1_000

# Staffing weights (PRD §3.2)
COUNSELOR_WEIGHT_X10 = 10
CIT_WEIGHT_HALF_X10 = 5            # CIT when cit_counts_as_half=true
CIT_WEIGHT_FULL_X10 = 10          # CIT when cit_counts_as_half=false

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Test clock defaults
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"      # server startup default; early tier vs 2026-07-01
