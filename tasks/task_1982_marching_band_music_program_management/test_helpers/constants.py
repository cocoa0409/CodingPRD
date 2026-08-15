"""Domain thresholds and numeric constants from PRD §3 calculations."""

# Logical clock (PRD §2.6): startup default before any clock call.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Rental fee variants (PRD §3.3).
SEMESTER_FLAT_FEE_CENTS = 15000
WEEKLY_RATE_CENTS = 2000

# Late return fee (PRD §3.3): whole weeks overdue x 500 cents.
LATE_FEE_PER_WEEK_CENTS = 500

# Cleaning batch pricing (PRD §3.4).
BASE_PRICE_CENTS = {
    "JACKET": 900,
    "BIBBERS": 700,
    "SHAKO": 450,
    "PLUME": 300,
    "GLOVES": 150,
}
HEAVY_SOILING_SURCHARGE_CENTS = 200
# Volume discount tiers by garment_count: 1-10 -> 0.00, 11-30 -> 0.15, 31+ -> 0.25
DISCOUNT_TIER_1_MAX = 10
DISCOUNT_TIER_2_MAX = 30
DISCOUNT_TIER_2_PCT = 0.15
DISCOUNT_TIER_3_PCT = 0.25

# Trip cost share (PRD §3.6).
SUBSIDY_CAP_PCT = 0.25

# Refund tiers in whole days to departure (PRD §3.6).
FULL_REFUND_DAYS = 14
HALF_REFUND_DAYS = 7

# Delinquency (PRD §2.8).
DEFAULT_DELINQUENCY_GRACE_CENTS = 2500

# Vehicle scheduling buffer (PRD §3.9): two hours applied to both ends.
LOADING_BUFFER_SECONDS = 7200

# Audition scoring (PRD §3.8).
W_MUSICIANSHIP = 0.5
W_MARCHING = 0.3
W_LEADERSHIP = 0.2
SINGLE_JUDGE_PENALTY = 0.95
SCORE_MIN = 0
SCORE_MAX = 100
CHALLENGE_WINDOW_DAYS = 7

# Budgets used as fixture defaults.
DEFAULT_MUSIC_BUDGET_CENTS = 100000
DEFAULT_REPAIR_BUDGET_CENTS = 50000
