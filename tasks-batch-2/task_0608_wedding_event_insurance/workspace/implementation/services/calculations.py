"""Calculation rules (scaffold §1.3, PRD §3.3-§3.9).

All money is integer cents. Where a fraction is introduced the direction
(ceil / floor) is pinned per the calculation contract and no other rounding is
applied.
"""
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

# rider_premium constants (scaffold §1.3).
RIDER_RATE = Decimal("0.015")        # 1.5% of scheduled value
RIDER_MIN_PREMIUM = 2500             # cents floor
RIDER_MAX_PREMIUM = 50000            # cents ceiling

# cancellation_refund constant (scaffold §1.3).
EARNED_MIN_RATIO = Decimal("0.25")   # carrier retains at least 25% after free-look

# claim_resubmit_cap constant (scaffold §1.3).
MAX_REVISIONS = 3

SECONDS_PER_DAY = 86400


def _ceil_cents(value):
    """Round a Decimal up to the next whole cent (integer)."""
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def _floor_cents(value):
    """Round a Decimal down to the whole cent below (integer)."""
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def rated_coverage_premium(product, total_attendance):
    """rated_premium_cents = base + per_guest * total_attendance (all integers)."""
    return product["base_premium_cents"] + product["per_guest_premium_cents"] * total_attendance


def rider_premium(scheduled_value_cents):
    """raw = ceil(scheduled_value * RIDER_RATE); clamp to [MIN, MAX] (clamp does not re-round)."""
    raw = _ceil_cents(Decimal(scheduled_value_cents) * RIDER_RATE)
    return min(RIDER_MAX_PREMIUM, max(RIDER_MIN_PREMIUM, raw))


def cancellation_refund(total_premium_cents, bind_at, now, free_look_days):
    """Compute (refund_due_cents, premium_earned_cents) on cancel.

    days_since_bind = floor((now - bind_at) / 86400 seconds).
    <= free_look_days  -> full refund, earned 0  (boundary inclusive).
    >  free_look_days  -> earned = ceil(total * 0.25); refund = total - earned.
    """
    elapsed_seconds = (now - bind_at).total_seconds()
    days_since_bind = int(elapsed_seconds // SECONDS_PER_DAY)
    if days_since_bind <= free_look_days:
        return total_premium_cents, 0
    earned = _ceil_cents(Decimal(total_premium_cents) * EARNED_MIN_RATIO)
    refund = total_premium_cents - earned
    return refund, earned


def claim_indemnity(product, coverage, claim_type, claimed_amount_cents):
    """approved = min(claimed, remaining_line, sublimit_cap), pinned order.

    remaining_line FIRST, sublimit_cap SECOND, three-way min THIRD.
    """
    remaining_line = product["coverage_limit_cents"] - coverage["consumed_limit_cents"]
    if claim_type in ("VENDOR_FAILURE", "CANCELLATION"):
        sublimit_cap = _floor_cents(
            Decimal(product["coverage_limit_cents"]) * Decimal(str(product["deposit_sublimit_pct"]))
        )
    else:
        sublimit_cap = product["coverage_limit_cents"]
    return min(claimed_amount_cents, remaining_line, sublimit_cap)
