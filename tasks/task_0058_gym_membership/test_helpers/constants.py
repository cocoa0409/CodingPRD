"""Domain thresholds — numeric constants from PRD §2.3, §3.3–§3.11.

Generic NON_EXISTENT_UUID comes from the framework.
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Recharge tier thresholds (PRD §3.3)
#   "amounts of at least 100,000 cents earn a 20% bonus, amounts of at least
#    50,000 cents earn a 10% bonus, amounts of at least 20,000 cents earn a
#    5% bonus, and amounts below 20,000 cents earn no bonus."
# ---------------------------------------------------------------------------
RECHARGE_TIER1_THRESHOLD_CENTS = 20_000     # 5%
RECHARGE_TIER2_THRESHOLD_CENTS = 50_000     # 10%
RECHARGE_TIER3_THRESHOLD_CENTS = 100_000    # 20%
RECHARGE_TIER1_BP = 500
RECHARGE_TIER2_BP = 1_000
RECHARGE_TIER3_BP = 2_000
MAX_RECHARGE_CENTS = 1_000_000              # PRD §3.3
BONUS_TTL_DAYS = 365                        # PRD §3.3

# ---------------------------------------------------------------------------
# Transfer fee floor (PRD §3.6 "the maximum of that result and 2,000 cents")
# ---------------------------------------------------------------------------
MIN_TRANSFER_FEE_CENTS = 2_000

# ---------------------------------------------------------------------------
# Renewal-quote bands (PRD §3.7)
# ---------------------------------------------------------------------------
EARLY_RENEWAL_WINDOW_DAYS = 30
URGENT_RENEWAL_WINDOW_DAYS = 7
URGENT_BONUS_DISCOUNT_BP = 500

# ---------------------------------------------------------------------------
# Trainer tier (PRD §3.11)
#   "at least 80 completed sessions promotes to GOLD, at least 40 promotes
#    to SILVER, otherwise BRONZE"
# ---------------------------------------------------------------------------
GOLD_THRESHOLD_SESSIONS = 80
SILVER_THRESHOLD_SESSIONS = 40

# Tier bonus rates (PRD §3.11)
SILVER_TIER_BONUS_BP = 1_000   # 10% on session commissions
GOLD_TIER_BONUS_BP = 2_000     # 20% on session commissions

# Session commission tier modifier (PRD §3.8)
SILVER_SESSION_BONUS_BP = 500    # +5 percentage points
GOLD_SESSION_BONUS_BP = 1_000    # +10 percentage points

# ---------------------------------------------------------------------------
# No-show grace (PRD §3.8)
#   "automatically when the clock crosses scheduled_starts_at plus 15 minutes
#    without a complete having been recorded"
# ---------------------------------------------------------------------------
PT_NO_SHOW_GRACE_MINUTES = 15

# ---------------------------------------------------------------------------
# PT no-show penalty (the PRD calls it "the no-show penalty constant"
# without nominating a specific value).  Tests that exercise the side-effect
# do not need this exact number — they only need the booking to flip and a
# debit row of `service_type=PT_SESSION` to be appended.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PT cancel windows (PRD §3.8: "at least 24 hours before scheduled_starts_at")
# Group cancel window (PRD §3.9: "at least 2 hours before starts_at")
# ---------------------------------------------------------------------------
PT_REFUND_WINDOW_HOURS = 24
GROUP_CANCEL_WINDOW_HOURS = 2

# ---------------------------------------------------------------------------
# Group-class instructor buffer (PRD §3.9: "a 30-minute buffer")
# ---------------------------------------------------------------------------
GROUP_CLASS_INSTRUCTOR_BUFFER_MINUTES = 30

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding utilities (PRD §2.7: "half-up rounding")
# ---------------------------------------------------------------------------
def round_half_up(value: float) -> int:
    """Half-up rounding to integer cents.

    PRD §2.7: "Computations that produce non-integer intermediate values
    are rounded to the nearest cent using half-up rounding (a value exactly
    halfway between two integers rounds up to the larger)."
    """
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


__all__ = [
    "RECHARGE_TIER1_THRESHOLD_CENTS",
    "RECHARGE_TIER2_THRESHOLD_CENTS",
    "RECHARGE_TIER3_THRESHOLD_CENTS",
    "RECHARGE_TIER1_BP",
    "RECHARGE_TIER2_BP",
    "RECHARGE_TIER3_BP",
    "MAX_RECHARGE_CENTS",
    "BONUS_TTL_DAYS",
    "MIN_TRANSFER_FEE_CENTS",
    "EARLY_RENEWAL_WINDOW_DAYS",
    "URGENT_RENEWAL_WINDOW_DAYS",
    "URGENT_BONUS_DISCOUNT_BP",
    "GOLD_THRESHOLD_SESSIONS",
    "SILVER_THRESHOLD_SESSIONS",
    "SILVER_TIER_BONUS_BP",
    "GOLD_TIER_BONUS_BP",
    "SILVER_SESSION_BONUS_BP",
    "GOLD_SESSION_BONUS_BP",
    "PT_NO_SHOW_GRACE_MINUTES",
    "PT_REFUND_WINDOW_HOURS",
    "GROUP_CANCEL_WINDOW_HOURS",
    "GROUP_CLASS_INSTRUCTOR_BUFFER_MINUTES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
]
