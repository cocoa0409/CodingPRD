"""Domain thresholds — numeric constants from the PRD's calculations and rules.

All monetary amounts are integer cents (PRD §2.5). Rating percentages are whole
integers; the combined rating is snapped to the nearest multiple of ten (PRD §3.6).
"""

# Monthly compensation base schedule, keyed by combined_rating_pct (PRD §3.8).
BASE_RATE_CENTS = {
    0: 0,
    10: 17500,
    20: 34600,
    30: 53600,
    40: 77200,
    50: 109900,
    60: 139500,
    70: 175800,
    80: 204400,
    90: 229600,
    100: 383150,
}

# Dependent additive amounts in cents (PRD §3.8), scaled by rating tier when
# combined_rating_pct >= 30.
SPOUSE_ADD_CENTS = 10000
PARENT_ADD_CENTS = 8000
CHILD_UNDER18_ADD_CENTS = 7000
CHILD_SCHOOL_ADD_CENTS = 23000

# Dependent-bump threshold (PRD §3.8): additions switch on only at >= 30.
DEPENDENT_RATING_THRESHOLD = 30

# Combined-rating rounding (PRD §3.6) and bilateral factor (PRD §3.7).
ROUND_TO_NEAREST = 10
BILATERAL_FACTOR_PCT = 10

# GI Bill tier day thresholds (PRD §3.10).
GI_BILL_DAYS_36_MONTHS = 1095  # -> 100
GI_BILL_DAYS_30_MONTHS = 912   # -> 90
GI_BILL_DAYS_24_MONTHS = 730   # -> 80
GI_BILL_DAYS_18_MONTHS = 547   # -> 70
GI_BILL_DAYS_12_MONTHS = 365   # -> 60
GI_BILL_DAYS_90 = 90           # -> 50
GI_BILL_DISABILITY_MIN_DAYS = 30  # disability-discharge short-circuit floor

# Housing allowance (PRD §3.11): MHA paid only when rate-of-pursuit strictly > 50.
RATE_OF_PURSUIT_FLOOR_PCT = 50

# Yellow Ribbon match (PRD §3.12): only the full 100% tier is eligible.
YELLOW_RIBBON_ELIGIBLE_TIER_PCT = 100

# Appeal cap (PRD §3.4 / §3.5): remand permitted only while remand_count < 2.
MAX_REMANDS = 2

# Voc Rehab eligibility (PRD §3.14): combined_rating_pct must be at least 20.
VOC_REHAB_MIN_RATING = 20

# Full Chapter 31 entitlement at creation (PRD §3.1).
VOC_REHAB_FULL_ENTITLEMENT_MONTHS = 48


# Convenient test defaults.
TEST_DEFAULTS = {
    "TOTAL_ACTIVE_DUTY_DAYS_TIER_100": 1200,
    "MONTHLY_HOUSING_RATE_CENTS": 200000,
}
