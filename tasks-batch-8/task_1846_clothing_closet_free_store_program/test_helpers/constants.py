"""Domain thresholds and constants from the PRD business rules."""

# Logical clock: the server stands at this instant before any clock call.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# A SORTING shift window that covers the default clock instant.
SORTING_SHIFT_START = "2026-07-31T22:00:00Z"
SORTING_SHIFT_END = "2026-08-01T04:00:00Z"

# Visit allowance arithmetic (PRD shopping-visit section).
BASE_ITEMS = 8
PER_MEMBER_ITEMS = 2
HOUSEHOLD_CAP = 16
HARDSHIP_MULTIPLIER = 1.5
HARD_VISIT_CAP = 24

# Visit frequency gate (PRD shopping-visit section).
COOLDOWN_DAYS = 14
MAX_VISITS_PER_30D = 3

# Rolling 30-day item cap (PRD distribution-lines section).
MAX_ITEMS_PER_30D = 30

# Per-visit category caps for general lines (PRD distribution-lines section).
CATEGORY_LINE_CAPS = {"COATS": 2, "INTERVIEW_ATTIRE": 1}

# Zone posture ratio (PRD zone occupancy section).
NEAR_FULL_RATIO = 0.8

# Voucher quota carryover cap (PRD referral-partner section).
MAX_CARRYOVER = 5

# Per-category estimated weights (kg) and per-kilogram credit rates (cents)
# from the PRD textile-recycling section.
EST_WEIGHT_KG = {
    "ADULT_TOPS": 0.40,
    "ADULT_BOTTOMS": 0.60,
    "CHILDRENS": 0.30,
    "COATS": 1.50,
    "INTERVIEW_ATTIRE": 0.80,
    "ACCESSORIES": 0.20,
}
RATE_CENTS_PER_KG = {
    "ADULT_TOPS": 45,
    "ADULT_BOTTOMS": 45,
    "CHILDRENS": 38,
    "COATS": 52,
    "INTERVIEW_ATTIRE": 60,
    "ACCESSORIES": 30,
}

# Final-settlement tiers (PRD textile-recycling section).
TIER1_MAX_KG = 100
TIER2_MAX_KG = 500
TIER1_RATE = 40
TIER2_RATE = 44
TIER3_RATE = 50
