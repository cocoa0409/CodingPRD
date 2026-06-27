"""Calculation rules (SCAFFOLD §1.3 / PRD §2.5, §3.3, §3.4, §3.6, §3.8, §3.9).

All money is integer cents. Percentage components are floored on their own before
summing (per-component floor, then add). The streak bonus is the lone exception
that rounds half-up per week before summing.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    RATE_CAP_BPS,
    CHECK_FEE_CENTS,
    SMALL_CASHOUT_FEE_BPS,
    LARGE_CASHOUT_CENTS,
    STREAK_BASE_CENTS,
    STREAK_GROWTH,
    MIN_PAYPAL_CENTS,
    MIN_CHECK_CENTS,
    MIN_GIFT_CARD_CENTS,
)


def floor_div(numer, denom):
    """Floor (truncate toward negative infinity for non-negative inputs)."""
    return numer // denom


# --------------------------------------------------------------------------
# reward_amount_computation
# --------------------------------------------------------------------------
def compute_online_reward(purchase_amount_cents, merchant, offer):
    """ONLINE variant: merchant.online_rate_bps + optional LINKED bonus_rate_bps,
    capped at RATE_CAP_BPS; floor of purchase * rate / 10000. Ignores rebate_cents.
    """
    base = merchant["online_rate_bps"]
    rate_bps = base
    if (
        offer is not None
        and offer["offer_type"] == "LINKED"
        and purchase_amount_cents >= offer["min_spend_cents"]
    ):
        rate_bps = base + offer["bonus_rate_bps"]
    rate_bps = min(rate_bps, RATE_CAP_BPS)
    return floor_div(purchase_amount_cents * rate_bps, 10000)


def compute_instore_reward(purchase_amount_cents, merchant, offer):
    """IN_STORE variant: floor percentage on instore_rate_bps PLUS flat
    RECEIPT_REBATE rebate_cents (when min_spend met), capped at purchase amount.
    Ignores bonus_rate_bps.
    """
    pct = floor_div(purchase_amount_cents * merchant["instore_rate_bps"], 10000)
    flat = 0
    if (
        offer is not None
        and offer["offer_type"] == "RECEIPT_REBATE"
        and purchase_amount_cents >= offer["min_spend_cents"]
    ):
        flat = offer["rebate_cents"]
    return min(flat + pct, purchase_amount_cents)


# --------------------------------------------------------------------------
# cashout_payout_and_fee
# --------------------------------------------------------------------------
def compute_cashout_fee(method, requested_amount_cents):
    """Return (fee_cents, net_payout_cents). Fee tier keyed strictly on GROSS
    requested_amount_cents (never on net)."""
    # STEP 1: select the fee tier on the gross amount.
    if method == "PAYPAL":
        pct_bps = 0
        flat = 0
    elif method == "CHECK":
        pct_bps = 0
        flat = CHECK_FEE_CENTS
    elif method == "GIFT_CARD":
        pct_bps = 0
        flat = 0
    else:
        pct_bps = 0
        flat = 0

    if method in ("PAYPAL", "GIFT_CARD"):
        if requested_amount_cents >= LARGE_CASHOUT_CENTS:
            pct_bps = 0
        else:
            pct_bps = SMALL_CASHOUT_FEE_BPS

    # STEP 2: fee from the tier chosen in STEP 1.
    fee_cents = flat + floor_div(requested_amount_cents * pct_bps, 10000)
    # STEP 3: net payout.
    net_payout_cents = requested_amount_cents - fee_cents
    return fee_cents, net_payout_cents


# --------------------------------------------------------------------------
# cashout_threshold_eligibility
# --------------------------------------------------------------------------
def cashout_minimum_for(method):
    return {
        "PAYPAL": MIN_PAYPAL_CENTS,
        "CHECK": MIN_CHECK_CENTS,
        "GIFT_CARD": MIN_GIFT_CARD_CENTS,
    }[method]


# --------------------------------------------------------------------------
# clawback_amount
# --------------------------------------------------------------------------
def compute_clawback(claim_amount_cents, returned_amount_cents, purchase_amount_cents):
    """Proportional clawback: ceil(amount * proportion), proportion clamped to
    [0,1]. A full return (returned >= purchase) claws the entire amount."""
    if purchase_amount_cents <= 0:
        return claim_amount_cents
    if returned_amount_cents >= purchase_amount_cents:
        return claim_amount_cents
    proportion = Decimal(returned_amount_cents) / Decimal(purchase_amount_cents)
    if proportion < 0:
        proportion = Decimal(0)
    if proportion > 1:
        proportion = Decimal(1)
    raw = Decimal(claim_amount_cents) * proportion
    return int(math.ceil(raw))


# --------------------------------------------------------------------------
# streak_bonus_computation
# --------------------------------------------------------------------------
def compute_streak_bonus(num_weeks):
    """Per-week rounding then sum (pinned order). Week w (1-based) bonus is
    round_half_up(STREAK_BASE_CENTS * (1 + STREAK_GROWTH * (w - 1)))."""
    total = 0
    base = Decimal(STREAK_BASE_CENTS)
    growth = Decimal(str(STREAK_GROWTH))
    for w in range(1, num_weeks + 1):
        raw = base * (Decimal(1) + growth * Decimal(w - 1))
        week_bonus = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += week_bonus
    return total
