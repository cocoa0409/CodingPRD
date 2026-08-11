"""Domain thresholds — numeric constants stated in PRD sections 2 and 3."""

# Provisional quote (PRD section 3.3)
DELIVERY_FEE_TIER1_LIMIT = 10000      # subtotal under this -> 2500
DELIVERY_FEE_TIER2_LIMIT = 30000      # subtotal from 10000 up to and including 29999 -> 1500
DELIVERY_FEE_TIER1 = 2500
DELIVERY_FEE_TIER2 = 1500
DELIVERY_FEE_TIER3 = 0
SETUP_FEE_CENTS = 1500
TIER1_DAYS = 6                        # days 1-6 at 100% of daily rate
TIER2_DAYS = 13                       # days 7-13 at 85%
TIER2_FACTOR = 0.85
TIER3_FACTOR = 0.70                   # days 14+ at 70%

# Late fee (PRD section 3.7)
GRACE_MINUTES = 240
HOURLY_LATE_FACTOR = 0.15
LATE_FEE_CAP_DAYS = 2

# Extension charge (PRD section 3.7)
EXT_TIER1_DAYS = 2
EXT_TIER1_FACTOR = 1.20
EXT_TIER2_FACTOR = 1.50

# Deposit hold / risk score (PRD sections 3.2 and 3.4)
RISK_MULTIPLIER_THRESHOLD = 70
RISK_MULTIPLIER = 1.5
LATE_WEIGHT = 15
DAMAGE_WEIGHT = 25
SUSPEND_THRESHOLD = 90
SCORE_CAP = 100

# Cancellation fee (PRD section 3.4)
CANCELLATION_FEE_PCT = 0.10

# Fiscal bounds (PRD sections 3.1 and 3.2)
COMMISSION_PCT_MAX = 0.30
PERCENT_OF_RENTAL_RATE_MAX = 0.25

# Standard fixture values
TEST_DEFAULTS = {
    "DAILY_RATE_CENTS": 3000,
    "DEPOSIT_AMOUNT_CENTS": 15000,
    "WEIGHT_KG": 12.0,
    "CLEANING_TURNAROUND_HOURS": 24,
    "DEEP_CLEAN_EVERY_CYCLES": 3,
    "ZONE": "Z1",
    "START_DATE": "2026-06-10",
    "END_DATE": "2026-06-13",
    "VEHICLE_CAPACITY_KG": 100.0,
}
