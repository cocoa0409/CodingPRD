"""Domain thresholds and constants from the PRD.

Numeric values used in PRD calculations (PRD §2.8, §3.5, §3.7, §3.9,
§3.10) and test defaults that exercise them.
"""
from __future__ import annotations


# Time / vesting constants (PRD §3.5)
DAYS_PER_MONTH = 30
SECONDS_PER_DAY = 86_400

# Repricing math (PRD §2.8, §3.7)
BPS_DIVISOR = 10_000
MIN_PRICE_CENTS = 1

# Tax-table constants (PRD §3.9)
LONG_TERM_HOLDING_MONTHS = 12
LONG_TERM_DISCOUNT_BPS = 1_000

# US-jurisdiction exercise tier (PRD §3.9):
# "the first 1,000,000 cents of taxable amount is taxed at 2200 basis points
#  (22 percent) and the remainder at 3700 basis points (37 percent)"
US_EXERCISE_SLAB_BREAKPOINT_CENTS = 1_000_000
US_EXERCISE_SLAB_1_BPS = 2200
US_EXERCISE_SLAB_2_BPS = 3700

# US vest flat slab (PRD §3.9): "for US/US on a vest, a single flat slab applies 2200 basis points"
US_VEST_FLAT_BPS = 2200

# UK-jurisdiction exercise tier (PRD §3.9):
# "for UK/UK on an exercise, the first 5,000,000 cents is taxed at 2000 bps
#  (20%) and the remainder at 4500 bps (45%)"
UK_EXERCISE_SLAB_BREAKPOINT_CENTS = 5_000_000
UK_EXERCISE_SLAB_1_BPS = 2000
UK_EXERCISE_SLAB_2_BPS = 4500

# CN-jurisdiction exercise tier (PRD §3.9):
# "for CN/CN on an exercise, the first 3,600,000 cents is taxed at 2000 bps
#  and the remainder at 4500 bps"
CN_EXERCISE_SLAB_BREAKPOINT_CENTS = 3_600_000
CN_EXERCISE_SLAB_1_BPS = 2000
CN_EXERCISE_SLAB_2_BPS = 4500

# SG-jurisdiction exercise flat (PRD §3.9):
# "for SG/SG on an exercise, all taxable amount is taxed at a flat 1500 bps (15%)"
SG_EXERCISE_FLAT_BPS = 1500

# Cross-residency treaty composites (PRD §3.9):
# "for cross-residency exercises where the plan is in the US and the grantee
#  resides in the UK or CN, a treaty composite rate of 3000 basis points
#  applies as a flat slab; for the US-plan, SG-resident exercise pair,
#  1500 basis points applies flat."
US_UK_CROSS_FLAT_BPS = 3000
US_CN_CROSS_FLAT_BPS = 3000
US_SG_CROSS_FLAT_BPS = 1500

# Departure post-exercise window day counts (PRD §3.10)
POST_DEPARTURE_RESIGNATION_DAYS = 90
POST_DEPARTURE_TERMINATION_DAYS = 180
POST_DEPARTURE_RETIREMENT_DAYS = 1_095
POST_DEPARTURE_DEATH_DAYS = 365
POST_DEPARTURE_GOOD_LEAVER_FLOOR_DAYS = 120  # UK / SG floor


# Convenient default inputs used by tests
TEST_DEFAULTS = {
    "PLAN_NAME": "Test Plan",
    "POOL_TOTAL": 10_000,
    "JURISDICTION_US": "US",
    "JURISDICTION_UK": "UK",
    "JURISDICTION_CN": "CN",
    "JURISDICTION_SG": "SG",
    "BATCH_LABEL": "Batch-A",
    "CLIFF_MONTHS": 12,
    "VESTING_TOTAL_MONTHS": 48,
    "VESTING_PERIOD_MONTHS": 3,
    "VESTING_ALGORITHM_ANNIVERSARY": "ANNIVERSARY_BATCH",
    "VESTING_ALGORITHM_CONTINUOUS": "CONTINUOUS_DAILY",
    "INITIAL_PRICE_CENTS": 5000,
    "GRANT_QUANTITY": 1200,
    "GRANT_FAIR_VALUE_CENTS": 5000,
}


__all__ = [
    "DAYS_PER_MONTH",
    "SECONDS_PER_DAY",
    "BPS_DIVISOR",
    "MIN_PRICE_CENTS",
    "LONG_TERM_HOLDING_MONTHS",
    "LONG_TERM_DISCOUNT_BPS",
    "US_EXERCISE_SLAB_BREAKPOINT_CENTS",
    "US_EXERCISE_SLAB_1_BPS",
    "US_EXERCISE_SLAB_2_BPS",
    "US_VEST_FLAT_BPS",
    "UK_EXERCISE_SLAB_BREAKPOINT_CENTS",
    "UK_EXERCISE_SLAB_1_BPS",
    "UK_EXERCISE_SLAB_2_BPS",
    "CN_EXERCISE_SLAB_BREAKPOINT_CENTS",
    "CN_EXERCISE_SLAB_1_BPS",
    "CN_EXERCISE_SLAB_2_BPS",
    "SG_EXERCISE_FLAT_BPS",
    "US_UK_CROSS_FLAT_BPS",
    "US_CN_CROSS_FLAT_BPS",
    "US_SG_CROSS_FLAT_BPS",
    "POST_DEPARTURE_RESIGNATION_DAYS",
    "POST_DEPARTURE_TERMINATION_DAYS",
    "POST_DEPARTURE_RETIREMENT_DAYS",
    "POST_DEPARTURE_DEATH_DAYS",
    "POST_DEPARTURE_GOOD_LEAVER_FLOOR_DAYS",
    "TEST_DEFAULTS",
]
