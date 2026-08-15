"""Domain thresholds — numeric constants named in the PRD (§3.1–§3.9)."""

# Logical clock startup value (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# 2026 federal poverty guideline, in cents, by household size (PRD §3.2).
FPL_2026_CENTS = {
    1: 1_565_000,
    2: 2_115_000,
    3: 2_665_000,
    4: 3_215_000,
    5: 3_765_000,
    6: 4_315_000,
    7: 4_865_000,
    8: 5_415_000,
}
FPL_ADDITIONAL_MEMBER_CENTS = 550_000  # per member beyond eight

# Delinquency thresholds (PRD §3.1; inclusive boundaries).
DELINQUENT_MIN_CENTS = 5_000
DELINQUENT_MIN_AGE_DAYS = 30
SEVERE_MIN_CENTS = 20_000
SEVERE_MIN_AGE_DAYS = 60

# DPA terms (PRD §3.4).
MIN_ARREARAGE_CENTS = 10_000            # fiscal floor for DPA creation
SHUTOFF_MIN_ARREARAGE_CENTS = 10_000    # shutoff eligibility / auto-cancel floor
FORGIVENESS_SHARE = {"TIER_1": 0.5, "TIER_2": 1.0 / 3.0, "TIER_3": 0.25, "NONE": 0.0}
DOWN_MIN_TIER_2_CENTS = 2_500           # $25.00
DOWN_MIN_OTHER_CENTS = 5_000            # $50.00
INSTALLMENT_MIN = 2
INSTALLMENT_MAX = 12
GRACE_DAYS = 5
CURE_WINDOW_DAYS = 15

# Bill-discount percentages keyed to enrollment tier (PRD §3.3).
DISCOUNT_PCT = {"TIER_1": 50, "TIER_2": 30, "TIER_3": 15}

# Medical certificates (PRD §3.6).
CERT_WINDOW_DAYS = 30
MAX_RENEWALS = 2

# Weather gate (PRD §3.6).
COLD_THRESHOLD_F = 32                   # exactly 32 triggers
HEAT_THRESHOLD_F = 95                   # exactly 95 triggers
WINTER_START_MONTH_DAY = "11-01"        # inclusive
WINTER_END_MONTH_DAY = "04-01"          # exclusive

# Shutoff notice (PRD §3.7).
NOTICE_DAYS = 15

# Reconnection fee schedule (PRD §3.7).
BASE_FEE_CENTS = 3_325                  # $33.25
AFTER_HOURS_RATE = 0.5
FEE_WAIVER_PCT = {"TIER_1": 100, "TIER_2": 30, "TIER_3": 25, "NONE": 0}
DEPOSIT_REQUIRED_CENTS = 7_500          # $75.00

# Referral expiry (PRD §3.9).
REFERRAL_EXPIRY_DAYS = 60

# Recertification interval (PRD §3.3).
RECERT_INTERVAL_DAYS = 365

# Common income presets that land on a specific tier at verify time.
# TIER_1: 500000*100 <= 150*1565000. TIER_2 (household 2): 3172500 < 3500000 <= 4230000.
# TIER_3 (household 1): 3130000 < 3500000 <= 3912500.
INCOME_TIER_1 = {"household_size": 1, "gross_annual_income_cents": 500_000,
                 "current_month_income_cents": 40_000}
INCOME_TIER_2 = {"household_size": 2, "gross_annual_income_cents": 3_500_000,
                 "current_month_income_cents": 300_000}
INCOME_TIER_3 = {"household_size": 1, "gross_annual_income_cents": 3_500_000,
                 "current_month_income_cents": 300_000}
