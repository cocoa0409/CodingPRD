"""Domain thresholds and defaults — numeric constants from the PRD's rules
(§2.5 logical-clock default, §2.8 royalty tiers, §3.3 classification floors,
§3.4 activation rule, §3.5 cancellation refund ladder, §3.6 late-fee cap and
loss horizon, §3.8 write-off aging)."""

# PRD §2.5: logical clock reads exactly this at server startup
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # PRD §2.8 house-size ladder
    "TIER1_MAX_SEATS": 199,
    "TIER2_MAX_SEATS": 399,
    "TIER3_MAX_SEATS": 799,
    # PRD §3.3 classification floors
    "PRO_PRICE_FLOOR_CENTS": 4000,
    "PRO_CAPACITY_FLOOR": 500,
    # PRD §3.6 late-fee cap: twice the deposit
    "LATE_FEE_CAP_MULTIPLE_OF_DEPOSIT": 2,
    # PRD §3.6 declare-lost horizon: due_date + 30 days
    "LOST_AFTER_DAYS": 30,
    # PRD §3.8 write-off aging: 180 days
    "WRITE_OFF_MIN_AGE_DAYS": 180,
    # PRD §3.5 breach fine floor (500,000 cents)
    "BREACH_FLOOR_CENTS": 500000,
    # PRD §3.5 cancellation refund ladder
    "FULL_REFUND_DAYS": 30,
    "PARTIAL_REFUND_DAYS": 7,
}

# Multipliers from PRD §2.8
TIER1_MULT_NUM, TIER1_MULT_DEN = 100, 100  # 1.00
TIER2_MULT_NUM, TIER2_MULT_DEN = 125, 100  # 1.25
TIER3_MULT_NUM, TIER3_MULT_DEN = 160, 100  # 1.60
TIER4_MULT_NUM, TIER4_MULT_DEN = 200, 100  # 2.00
AMATEUR_MULT_NUM, AMATEUR_MULT_DEN = 100, 100  # 1.00
PROFESSIONAL_MULT_NUM, PROFESSIONAL_MULT_DEN = 150, 100  # 1.50

TEST_DEFAULTS = {
    "BASE_FLAT_FEE_CENTS": 50000,
    "GROSS_PERCENT_BP": 0,
    "PERUSAL_FEE_CENTS": 500,
    "RENTAL_DEPOSIT_CENTS": 20000,
    "LATE_FEE_PER_DAY_CENTS": 500,
    "RESTRICTED_LATE_FEE_PER_DAY_CENTS": 1500,
    "RECORDING_ROYALTY_FLAT_CENTS": 30000,
}
