"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework. These literals appear in
PRD §3.3 (hazard scoring), §3.4 (line-item unit costs), §3.5 (surcharges and
emergency multiplier), and §3.9 (booking overtime).
"""

# Hazard scoring (PRD §3.3)
DBH_TIER_LARGE_IN = 36          # >= 36 in -> 50 points
DBH_TIER_MED_IN = 18           # >= 18 in -> 30 points (boundary inclusive)
DBH_SMALL_POINTS = 10
DBH_MED_POINTS = 30
DBH_LARGE_POINTS = 50
LEAN_STEP_DEG = 5
LEAN_STEP_POINTS = 10
LEAN_CAP = 30
DECAY_POINTS = 20
TIER_SEVERE_MIN = 70           # score >= 70 -> SEVERE
TIER_MODERATE_MIN = 40         # score >= 40 -> MODERATE (boundary inclusive)

# Line-item unit costs in cents (PRD §3.4)
REMOVAL_SMALL_CENTS = 45000    # dbh < 18 in
REMOVAL_MED_CENTS = 95000      # 18 <= dbh < 36 in
REMOVAL_LARGE_CENTS = 180000   # dbh >= 36 in
STUMP_CENTS_PER_INCH = 1200
HAUL_OFF_CENTS_PER_TON = 8500
UTILITY_LINE_ITEM_CENTS = 60000

# Surcharges (PRD §3.5, §3.10)
HAZARD_PCT_SEVERE = 0.20
HAZARD_PCT_MODERATE = 0.10
UTILITY_PER_TREE_CENTS = 25000
EMERGENCY_MULTIPLIER = 1.5
DEFAULT_HERITAGE_SURCHARGE_PCT = 0.15

# Booking overtime (PRD §3.9)
OT_THRESHOLD_HOURS = 8
OT_MULTIPLIER = 1.5

# Equipment mobilization buffer default (PRD §3.1)
DEFAULT_MOBILIZATION_BUFFER_MINUTES = 30

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
