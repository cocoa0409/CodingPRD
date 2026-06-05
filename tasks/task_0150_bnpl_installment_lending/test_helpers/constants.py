"""Domain thresholds — numeric constants from the BNPL PRD §3 calculations."""

# Eligibility / credit tiers (PRD §3.1)
SCORE_TIER_1 = 580          # below -> base limit 0
SCORE_TIER_2 = 670          # [580, 670) -> 50000
SCORE_TIER_3 = 740          # [670, 740) -> 200000; >= 740 -> 500000
LIMIT_TIER_2_CENTS = 50000
LIMIT_TIER_3_CENTS = 200000
LIMIT_TIER_4_CENTS = 500000
INCOME_FACTOR = 0.10        # income cap = floor(annual_income_cents * 0.10)

# Finance charge / pricing (PRD §3.2, §3.4)
MONTHLY_APR_BPS = 1990      # 19.90% fixed for MONTHLY; 0 for PAY_IN_4

# Installment schedule intervals (PRD §3.4)
PAY_IN_4_INTERVAL_DAYS = 14
MONTHLY_INTERVAL_DAYS = 30
PAY_IN_4_INSTALLMENT_COUNT = 4

# Late fee assessment (PRD §3.6)
GRACE_DAYS = 10
LATE_FEE_RATE = 0.05
LATE_FEE_FLOOR_CENTS = 700   # $7.00 minimum
LATE_FEE_CAP_CENTS = 1500    # $15.00 cap

# Delinquency posture (PRD §3.6)
DELINQUENT_DAYS = 30

# Settlement hold default (PRD §3.1)
DEFAULT_SETTLEMENT_HOLD_DAYS = 2

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
