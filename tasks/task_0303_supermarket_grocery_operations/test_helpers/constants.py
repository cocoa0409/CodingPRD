"""Domain thresholds — numeric constants from the PRD's calculations and gates."""

# Receiving fiscal variance gate (PRD §3.2): tolerance 500 bps (5.00%).
RECEIVE_VARIANCE_TOLERANCE_BPS = 500

# Loyalty tier breakpoints (PRD §3.9), inclusive (>=).
SILVER_THRESHOLD_CENTS = 50_000
GOLD_THRESHOLD_CENTS = 200_000

# Loyalty point accrual: 1 point per whole dollar of total, multiplied by tier rate.
POINTS_PER_DOLLAR = 1
BASIC_MULTIPLIER = 1.0
SILVER_MULTIPLIER = 1.5
GOLD_MULTIPLIER = 2.0

# Department default shrink alert (PRD §3.1).
DEFAULT_SHRINK_ALERT_BPS = 200

# Weighed-item conversion: 1000 milli-units == 1 pound (PRD §2.5).
MILLI_PER_POUND = 1000

# Pagination (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
