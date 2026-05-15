"""Pure calculation rules from SCAFFOLD §1.3 — all monetary values in integer cents.

All rounding uses ROUND_HALF_UP per PRD §2.5. Order of operations is
multiplication first, division by 10000 second, rounding last. Cap
comparisons evaluate the unrounded intermediates.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from ..constants import (
    DAILY_PENALTY_BPS,
    FIRST_AUCTION_DISCOUNT_BPS,
    INC_TIER_1_CENTS,
    INC_TIER_2_CENTS,
    INC_TIER_3_CENTS,
    INC_TIER_4_CENTS,
    MAX_PENALTY_BPS,
    REAUCTION_DISCOUNT_BPS,
    TIER_1_MAX_CENTS,
    TIER_2_MAX_CENTS,
    TIER_3_MAX_CENTS,
    W_ALTERNATING,
    W_IDENTICAL_INC,
    W_SHARED_IP,
    W_YOUNG_ACCOUNT,
    YOUNG_ACCOUNT_DAYS,
)


def _round_half_up_int(numerator: int, denominator: int) -> int:
    """Round-half-up of numerator/denominator to integer cents (Decimal-based)."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


# ---------------------------------------------------------------------------
# starting_price_calc
# ---------------------------------------------------------------------------
def starting_price_first(assessment_value_cents: int) -> int:
    """Round 1: assessment × (1 - FIRST_AUCTION_DISCOUNT_BPS/10000)."""
    return _round_half_up_int(
        assessment_value_cents * (10000 - FIRST_AUCTION_DISCOUNT_BPS),
        10000,
    )


def starting_price_reauction(prior_starting_price_cents: int) -> int:
    """Round > 1: prior_starting × (1 - REAUCTION_DISCOUNT_BPS/10000)."""
    return _round_half_up_int(
        prior_starting_price_cents * (10000 - REAUCTION_DISCOUNT_BPS),
        10000,
    )


# ---------------------------------------------------------------------------
# deposit_amount_calc
# ---------------------------------------------------------------------------
def deposit_amount_fixed(deposit_fixed_cents: int) -> int:
    return int(deposit_fixed_cents)


def deposit_amount_percent(starting_price_cents: int, deposit_percent_bps: int) -> int:
    return _round_half_up_int(starting_price_cents * deposit_percent_bps, 10000)


# ---------------------------------------------------------------------------
# bid_increment_ladder
# ---------------------------------------------------------------------------
def bid_increment_for(base_cents: int) -> int:
    if base_cents < TIER_1_MAX_CENTS:
        return INC_TIER_1_CENTS
    if base_cents < TIER_2_MAX_CENTS:
        return INC_TIER_2_CENTS
    if base_cents < TIER_3_MAX_CENTS:
        return INC_TIER_3_CENTS
    return INC_TIER_4_CENTS


def min_next_bid(
    current_high_cents: Optional[int], starting_price_cents: int
) -> tuple[int, int]:
    """Return (min_next_bid, applied_increment) per SCAFFOLD bid_increment_ladder.

    When current_high is None the very first bid may equal starting_price exactly;
    the applied_increment in that case is the ladder value for the starting_price
    (used by collusion detection).
    """
    if current_high_cents is None:
        base = starting_price_cents
        inc = bid_increment_for(base)
        return base, inc
    base = current_high_cents
    inc = bid_increment_for(base)
    return base + inc, inc


# ---------------------------------------------------------------------------
# late_payment_penalty
# ---------------------------------------------------------------------------
def late_payment_penalty(
    balance_due_cents: int, days_overdue: int
) -> int:
    """Linear penalty up to cap.

    Formula (full precision):
        uncapped = balance × DAILY_PENALTY_BPS × days_overdue / 10000
        cap      = balance × MAX_PENALTY_BPS / 10000
        result   = round_half_up( min(uncapped, cap) )
    Cap comparison uses the unrounded intermediates.
    """
    if days_overdue <= 0 or balance_due_cents <= 0:
        return 0
    uncapped_num = Decimal(balance_due_cents) * Decimal(DAILY_PENALTY_BPS) * Decimal(days_overdue)
    cap_num = Decimal(balance_due_cents) * Decimal(MAX_PENALTY_BPS)
    chosen = uncapped_num if uncapped_num < cap_num else cap_num
    q = (chosen / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def days_overdue(now_dt, due_at_dt) -> int:
    """ceil(elapsed_seconds / 86400)."""
    if due_at_dt is None:
        return 0
    delta = now_dt - due_at_dt
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))


# ---------------------------------------------------------------------------
# balance_due_calc — simple subtraction in integer cents
# ---------------------------------------------------------------------------
def balance_due(winning_amount_cents: int, deposit_amount_cents: int) -> int:
    return int(winning_amount_cents) - int(deposit_amount_cents)


# ---------------------------------------------------------------------------
# collusion_risk_score
# ---------------------------------------------------------------------------
def young_account_flag(account_age_days: int) -> int:
    return 1 if int(account_age_days) < YOUNG_ACCOUNT_DAYS else 0


def per_peer_score(
    shared_ip: int,
    alternating_pattern: int,
    identical_increment: int,
    young_account: int,
) -> int:
    return (
        W_SHARED_IP * shared_ip
        + W_ALTERNATING * alternating_pattern
        + W_IDENTICAL_INC * identical_increment
        + W_YOUNG_ACCOUNT * young_account
    )
