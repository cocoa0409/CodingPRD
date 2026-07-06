"""Domain thresholds — numeric constants from PRD."""

# Reorder window and discount (PRD §3.5, §3.2)
REORDER_WINDOW_DAYS = 365
REORDER_DISCOUNT_PCT = 0.10

# Rush window and tier percentages (PRD §3.4)
RUSH_MIN_DAYS = 3
RUSH_MAX_DAYS = 14
RUSH_TIER_15D_PCT = 0.15
RUSH_TIER_7D_PCT = 0.30

# Lead-day adjustments (PRD §3.4)
ADDRESSING_LEAD_DAYS = 3
RUSH_LEAD_DAY_SPEEDUP = 4

# Revision fee (PRD §3.6)
REVISION_FEE_CENTS = 2500
REVISION_FREE_COUNT = 3

# Addressing daily capacity (PRD §3.7)
ADDRESSING_DAILY_CAPACITY = 500

# Quantity tiers for line-item pricing (PRD §3.3)
QUANTITY_TIERS = [
    (1, 49, 1.00),
    (50, 99, 1.00),
    (100, 199, 0.90),
    (200, 499, 0.80),
    (500, 999_999, 0.70),
]


TEST_DEFAULTS = {
    "PAPER_BASE_PRICE_CENTS": 500,
    "PAPER_LEAD_DAYS": 7,
    "FINISH_SURCHARGE_CENTS": 100,
    "FINISH_ADDITIONAL_LEAD_DAYS": 5,
    "WEDDING_DEPOSIT_PCT": 0.5,
    "WEDDING_MIN_QTY": 50,
    "WEDDING_PROOF_EXPIRY_DAYS": 14,
    "DEFAULT_QTY": 150,
    "DEFAULT_ADDRESSING_UNIT_PRICE_CENTS": 200,
    "DEFAULT_DEPOSIT_AMOUNT": 41250,  # 82500 * 0.5 subtotal deposit at qty=150
    "DEFAULT_SUBTOTAL": 82500,  # 500*150*0.9 + 100*150
}
