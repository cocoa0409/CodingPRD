"""Domain thresholds — numeric constants from the Rent-To-Own Home PRD calculations (§3)."""

# §3.7: "the tenant's `credit_score` must be at least 620, the minimum conversion score".
MIN_CONVERSION_SCORE = 620

# §3.8: "only once the `missed_payment_count` has reached at least three (the maximum
# tolerated missed payments)".
MAX_MISSED_PAYMENTS = 3

# §3.4: "a late-fee rate of five percent".
LATE_FEE_PCT = 0.05

# §3.2 defaults.
DEFAULT_MAX_CREDIT_PCT = 0.20
DEFAULT_GRACE_DAYS = 5
DEFAULT_MAINTENANCE_THRESHOLD_CENTS = 50000
DEFAULT_OPTION_FEE_CREDITABLE = True

# §3.1: credit_score bounds.
MIN_CREDIT_SCORE = 300
MAX_CREDIT_SCORE = 850
