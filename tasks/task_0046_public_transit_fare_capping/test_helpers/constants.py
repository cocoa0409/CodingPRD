"""Domain thresholds and reusable literal values from the PRD's pricing and
risk-score rules. NON_EXISTENT_UUID comes from the framework.
"""

# Risk-score weights (§3.2). Each rejected tap contributes 15, each reversed 8,
# and a low-balance flag contributes 20; the low-balance flag fires when the
# rider's default active funding source holds a balance below 500.
RISK_WEIGHTS = {
    "REJECT": 15,
    "REVERSAL": 8,
    "LOW_BALANCE": 20,
}
LOW_BALANCE_FLOOR_CENTS = 500
RISK_SCORE_MAX = 100

# Pagination defaults (§2.3).
PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}

# Default transfer-rule / discount defaults applied at fare-product creation (§3.1).
FARE_PRODUCT_DEFAULTS = {
    "transfer_window_minutes": 120,
    "transfer_discount_pct": 1.0,
    "reduced_fare_pct": 0.5,
}

# A well-formed UUID guaranteed not to resolve to any created resource.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
