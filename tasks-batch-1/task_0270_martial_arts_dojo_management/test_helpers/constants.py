"""Domain thresholds — numeric constants from the PRD calculations and gates.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Balance threshold (100 dollars = 10000 cents) used for auto-suspend/unsuspend
# and as the promotion-test balance ceiling (PRD §3.3, §3.5).
SUSPEND_THRESHOLD_CENTS = 10000
TEST_BALANCE_CEILING_CENTS = 10000

# Promotion-test pass boundary (PRD §3.5): a score of at least 70 passes.
PASS_SCORE = 70

# Family-discount tiers (PRD §3.2).
FAMILY_TIER = {
    "TIER_2_PCT": 0.10,   # exactly 2 counted members
    "TIER_3_PCT": 0.15,   # exactly 3 counted members
    "TIER_4_PLUS_PCT": 0.20,  # 4 or more counted members (cap)
}

# Pro-shop belt-loyalty discount tiers (PRD §2.8).
PRO_SHOP_BELT = {
    "HIGH_PCT": 0.15,     # highest ACTIVE rank_order >= 5
    "MID_PCT": 0.10,      # highest ACTIVE rank_order >= 2
    "HIGH_RANK_ORDER": 5,
    "MID_RANK_ORDER": 2,
}

# Early-termination buyout (PRD §3.6).
BUYOUT_RATE = 0.50
BUYOUT_CAP_CENTS = 50000

# Readiness scoring weights (PRD §3.5).
ATTENDANCE_WEIGHT = 40
DAYS_WEIGHT = 60

# Tournament age divisions (PRD §3.7).
TEEN_MIN_AGE = 13
ADULT_MIN_AGE = 18
MASTERS_MIN_AGE = 40

# Allowed contract term lengths (PRD §3.6).
ALLOWED_TERM_MONTHS = [3, 6, 12, 24]
