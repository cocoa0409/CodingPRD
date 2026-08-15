"""Domain thresholds and defaults — numeric constants from the PRD."""

# PRD §2.4: the logical clock reads exactly 2026-08-01T00:00:00Z at startup.
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# PRD §3.1: line-level commercial-term defaults.
DEFAULT_CANCEL_WINDOW_DAYS = 30
DEFAULT_RESCHEDULE_WINDOW_DAYS = 20
DEFAULT_ALLOCATION_POLICY = "BACKLOG_BASIS"

# PRD §3.9: restocking fee tiers and excess-return cap.
FEE_TIER_1_MAX_DAYS = 90
FEE_TIER_1_PCT = 0.10
FEE_TIER_2_MAX_DAYS = 180
FEE_TIER_2_PCT = 0.25
BUYBACK_WINDOW_DAYS = 180
BUYBACK_CAP_PCT_NUM = 15  # floor(0.15 * trailing_12mo_purchases_cents)
BUYBACK_CAP_WINDOW_DAYS = 365

# Shared commercial defaults used by factories.
STANDARD_COST_CENTS = 1000
BOOK_PRICE_CENTS = 1500
AMPLE_CREDIT_LIMIT_CENTS = 100_000_000

# Standard operator ids for the opaque roles (PRD §2.1).
WAREHOUSE_USER_ID = "wh-01"
INSPECTOR_USER_ID = "qi-01"
