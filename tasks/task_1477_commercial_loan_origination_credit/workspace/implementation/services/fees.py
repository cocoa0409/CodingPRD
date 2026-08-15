"""Origination fee (tiered) and participation fee allocation."""
from decimal import Decimal

from services.money import round_half_up_cents

TIER1_CAP_CENTS = 100000000      # first $1,000,000.00
TIER2_CAP_CENTS = 400000000      # next $4,000,000.00
TIER1_RATE = Decimal("0.0100")
TIER2_RATE = Decimal("0.0075")
TIER3_RATE = Decimal("0.0050")


def origination_fee_cents(amount_cents):
    """Per-tier slice rounded half-up to cents, then summed in tier order."""
    tier1_base = min(amount_cents, TIER1_CAP_CENTS)
    tier2_base = min(max(amount_cents - TIER1_CAP_CENTS, 0), TIER2_CAP_CENTS)
    tier3_base = max(amount_cents - TIER1_CAP_CENTS - TIER2_CAP_CENTS, 0)
    fee = (round_half_up_cents(Decimal(tier1_base) * TIER1_RATE)
           + round_half_up_cents(Decimal(tier2_base) * TIER2_RATE)
           + round_half_up_cents(Decimal(tier3_base) * TIER3_RATE))
    return fee


def participation_fee_share_cents(letter, allocated_amount_cents):
    """Per-share round-half-up allocation (mode b); the bank hold is the
    unrounded remainder absorber (see exposure.bank_hold_fee_cents)."""
    share = (Decimal(letter['origination_fee_cents']) * Decimal(allocated_amount_cents)
             / Decimal(letter['committed_amount_cents']))
    return round_half_up_cents(share)
