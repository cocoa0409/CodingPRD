"""Domain thresholds — numeric constants from the PRD calculations."""

# Consumption conversion
THERM_DECIMALS = 1

# Bill charges
PAYMENT_TERM_DAYS = 21

# Budget installment
BUDGET_MONTHS = 12

# Low-income eligibility (federal poverty line)
FPL_BASE_CENTS = 1_509_000          # $15,090 annual for a household of 1
FPL_PER_PERSON_CENTS = 532_000      # +$5,320 per additional member
TIER_1_FPL_RATIO = 1.00
TIER_2_FPL_RATIO = 1.50

# Low-income per-cycle credit
TIER_1_DISCOUNT_PCT = 0.20
TIER_2_DISCOUNT_PCT = 0.10
TIER_1_MONTHLY_CAP_CENTS = 4000
TIER_2_MONTHLY_CAP_CENTS = 2500

# Deposit requirement
DEPOSIT_RES_CENTS = 15000
DEPOSIT_COM_CENTS = 40000
DELINQUENCY_MULTIPLIER = 1.5
DEPOSIT_WAIVE_ONTIME_COUNT = 12
DEPOSIT_REFUND_ONTIME_COUNT = 12

# Shutoff eligibility
SHUTOFF_THRESHOLD_CENTS = 7500      # $75.00 past-due floor

# Winter moratorium
MORATORIUM_MONTHS = [11, 12, 1, 2, 3]

# Ticket severity SLAs (minutes)
GRADE_1_SLA_MIN = 60
GRADE_2_SLA_MIN = 240
GRADE_3_SLA_MIN = 1440

# Canonical RES bill literals (clock 2026-02, RES-1 fixed 1200 / dist 15 / btu 1.025,
# PGA commodity 40 / refund 5 -> eff 35; meter CCF install 1000, read 1100 ->
# ccf 100 -> therms 102.5).
CANONICAL_THERMS = 102.5
CANONICAL_COMMODITY_CENTS = 3588
CANONICAL_DISTRIBUTION_CENTS = 1538
CANONICAL_FIXED_CENTS = 1200
CANONICAL_AMOUNT_DUE_CENTS = 6326

# Test default budget installment used in dual-variant designs.
CANONICAL_BUDGET_INSTALLMENT_CENTS = 8000   # round(96000 / 12)
