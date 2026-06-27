"""Domain thresholds and reusable test defaults from PRD calculations.

The PRD's calculations carry no fixed numeric constants of their own; the
thresholds (no-show strike limit, punch reward threshold, grace minutes) are
per-shop config supplied at shop creation. These defaults match PRD §3.1.
"""

# PRD-declared shop-config defaults (§3.1)
PRD_SHOP_DEFAULTS = {
    "product_commission_pct": 0,
    "no_show_fee_cents": 0,
    "no_show_strike_limit": 3,
    "late_grace_minutes": 10,
    "punch_reward_threshold": 10,
    "punch_reward_value_cents": 0,
}

# Reusable fixed instant for deterministic time-based tests.
DEFAULT_CLOCK = "2026-06-10T08:00:00Z"
SHIFT_START = "2026-06-10T09:00:00Z"
SHIFT_END = "2026-06-10T18:00:00Z"
BUSINESS_DATE = "2026-06-10"
