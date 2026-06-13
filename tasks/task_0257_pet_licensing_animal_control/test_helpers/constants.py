"""Domain thresholds and numeric constants from the PRD fee/penalty rules (§3.6).

All monetary amounts are integer cents (PRD §2.7).
"""

# License fee (PRD §3.6)
BASE_RATE_INDIVIDUAL_CENTS = 4000      # INDIVIDUAL base ($40)
BASE_RATE_KENNEL_CENTS = 12000         # KENNEL per-pet base ($120)
ALTERED_FACTOR = 0.5                   # altered pets pay half
UNALTERED_FACTOR = 1.0                 # unaltered pets pay full
KENNEL_DISCOUNT_PCT = 0.05             # 5% off per occupied slot
KENNEL_DISCOUNT_FLOOR_PCT = 0.6        # discounted fee never below 60% of base

# Dangerous-dog surcharge (PRD §3.6)
SURCHARGE_BASE_CENTS = 5000            # $50 base
SEVERITY_MULT_BITE = 1.0
SEVERITY_MULT_ATTACK = 2.0
SEVERITY_MULT_NUISANCE = 0.5
SURCHARGE_MIN_CENTS = 3000             # floor: never below $30

# Late penalty (PRD §3.6)
GRACE_DAYS = 30
PENALTY_TIER_1_CENTS_PER_DAY = 200     # days_late <= 30
PENALTY_TIER_1_MAX_DAYS = 30
PENALTY_TIER_2_CENTS_PER_DAY = 500     # days_late > 30

# Lost/found match scoring (PRD §3.8)
W_SPECIES = 10
W_ZIP = 20
W_TAG_EXACT = 100
MATCH_MIN_SCORE = 20                   # must reach at least ZIP-level agreement

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


THRESHOLDS = {
    "BASE_RATE_INDIVIDUAL_CENTS": BASE_RATE_INDIVIDUAL_CENTS,
    "BASE_RATE_KENNEL_CENTS": BASE_RATE_KENNEL_CENTS,
    "SURCHARGE_BASE_CENTS": SURCHARGE_BASE_CENTS,
    "SURCHARGE_MIN_CENTS": SURCHARGE_MIN_CENTS,
    "GRACE_DAYS": GRACE_DAYS,
    "PENALTY_TIER_1_MAX_DAYS": PENALTY_TIER_1_MAX_DAYS,
    "MATCH_MIN_SCORE": MATCH_MIN_SCORE,
}
