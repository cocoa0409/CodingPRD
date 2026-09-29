"""The cancellation refund calculation (PRD 3.7).

The unearned FRACTION is identical in both variants; only the money differs.
The fee tier is keyed on unearned_premium_cents, never on the refund.
"""

from util import D, parse_date, rhu_cents
from services.constants import (
    FEE_LARGE_PCT,
    FEE_MEDIUM_CENTS,
    FEE_SMALL_CENTS,
    FEE_TIER_1_CENTS,
    FEE_TIER_2_CENTS,
    POLICY_TERM_DAYS,
    SHORT_RATE_FACTOR,
)


def unearned_fraction(policy, cancellation_date):
    effective = parse_date(policy["effective_date"])
    days_in_force = (cancellation_date - effective).days
    remaining = POLICY_TERM_DAYS - days_in_force
    if remaining < 0:
        remaining = 0
    return D(remaining) / D(POLICY_TERM_DAYS)


def compute(policy, cancel_reason, cancellation_date):
    """Return (unearned_fraction, unearned_premium_cents, fee_cents, refund_cents)."""
    fraction = unearned_fraction(policy, cancellation_date)
    product = D(policy["annual_premium_cents"]) * fraction
    if cancel_reason == "POLICYHOLDER_REQUEST":
        # SHORT_RATE — the same product multiplied by 0.90 before rounding.
        unearned = rhu_cents(product * SHORT_RATE_FACTOR)
    else:
        # PRO_RATA — PLAN_INITIATED and TAKEOUT_ELECTION.
        unearned = rhu_cents(product)

    if cancel_reason == "TAKEOUT_ELECTION":
        fee = 0
    elif unearned == 0:
        fee = 0
    elif unearned <= FEE_TIER_1_CENTS:
        fee = FEE_SMALL_CENTS
    elif unearned <= FEE_TIER_2_CENTS:
        fee = FEE_MEDIUM_CENTS
    else:
        fee = rhu_cents(D(unearned) * FEE_LARGE_PCT)

    refund = unearned - fee
    if refund < 0:
        refund = 0
    return fraction, unearned, fee, refund
