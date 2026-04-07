"""
E-Commerce Marketplace — domain constants and test defaults (scaffold Table 3).
"""

# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------

RESERVATION_TIMEOUT_MINUTES = 30

# ---------------------------------------------------------------------------
# Commission tiers  (tiered / marginal rate)
# ---------------------------------------------------------------------------

COMMISSION_TIERS = [
    {"lower": 0,     "upper": 10_000, "rate": 0.08},
    {"lower": 10_000, "upper": 50_000, "rate": 0.05},
    {"lower": 50_000, "upper": float("inf"), "rate": 0.03},
]

# ---------------------------------------------------------------------------
# Discount application
# ---------------------------------------------------------------------------

# Floor for running_total when stacking promotions.
MIN_ORDER_TOTAL = 0.01

# ---------------------------------------------------------------------------
# Sensible test defaults
# ---------------------------------------------------------------------------

TEST_DEFAULTS = {
    # Product
    "product_price": 99.99,
    "product_inventory": 100,

    # Promotion — percentage type
    "promo_discount_pct": 10.0,       # 10 %
    "promo_budget": 5000.00,
    "promo_max_uses": 1000,
    "promo_priority": 1,

    # Promotion — fixed-amount type
    "promo_discount_fixed": 5.00,

    # Order
    "order_quantity": 2,

    # Payment
    "payment_method": "CREDIT_CARD",

    # Settlement
    "settlement_period_days": 14,

    # Inventory reservation
    "reservation_timeout_minutes": RESERVATION_TIMEOUT_MINUTES,
}
