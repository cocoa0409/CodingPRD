"""Domain thresholds and global constants (PRD §2.5, §2.10, §3.4, §3.6, §3.7, §3.8).

All monetary amounts are integer cents. Rate/fraction fields preserve input precision.
"""

# Loyalty-tier thresholds on lifetime_net_sales_cents (inclusive >=), PRD §3.7.
PREMIER_THRESHOLD_CENTS = 1_000_000   # $10,000
ELITE_THRESHOLD_CENTS = 5_000_000     # $50,000

# Commission tier discounts and floor, PRD §3.4.
PREMIER_DISCOUNT_PCT = 0.03
ELITE_DISCOUNT_PCT = 0.05
MIN_COMMISSION_PCT = 0.05

# Buyer charges and refunds, PRD §3.6 / §3.8.
SALES_TAX_PCT = 0.08
RESTOCKING_PCT = 0.10

# Payout hold and offer TTL, PRD §3.7 / §3.5.
PAYOUT_HOLD_DAYS = 1
OFFER_TTL_HOURS = 72

# White-glove concierge travel buffer, PRD §3.2.
TRAVEL_BUFFER_MINUTES = 60

# Logical clock startup default, PRD §2.10.
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

THRESHOLDS = {
    "PREMIER_THRESHOLD_CENTS": PREMIER_THRESHOLD_CENTS,
    "ELITE_THRESHOLD_CENTS": ELITE_THRESHOLD_CENTS,
    "PREMIER_DISCOUNT_PCT": PREMIER_DISCOUNT_PCT,
    "ELITE_DISCOUNT_PCT": ELITE_DISCOUNT_PCT,
    "MIN_COMMISSION_PCT": MIN_COMMISSION_PCT,
    "SALES_TAX_PCT": SALES_TAX_PCT,
    "RESTOCKING_PCT": RESTOCKING_PCT,
    "PAYOUT_HOLD_DAYS": PAYOUT_HOLD_DAYS,
    "OFFER_TTL_HOURS": OFFER_TTL_HOURS,
    "TRAVEL_BUFFER_MINUTES": TRAVEL_BUFFER_MINUTES,
}
