"""Closing calculations (PRD 3.9) and the LOI deposit minimum (PRD 3.4).

commission_settlement (runs FIRST at closing, evaluation order pinned):
  base := agreed_price_usd - credits_total_usd
  sole := round_half_up(min(base, TIER1_LIMIT) * TIER1_RATE
                        + max(base - TIER1_LIMIT, 0) * TIER2_RATE, 2)
  SOLE_AGENCY:  commission := sole
  DUAL_AGENCY:  commission := round_half_up(sole + base * DUAL_BUYER_SIDE_RATE, 2)

closing_settlement (runs SECOND):
  settlement_buyer_due_usd  := agreed - credits - escrow.deposit_amount_usd
  settlement_seller_net_usd := agreed - commission_amount_usd

deposit_requirement (LOI submission):
  minimum := round_half_up(offer_price_usd * MIN_DEPOSIT_PCT, 2)
  deposit >= minimum passes; exact equality passes.
"""
from decimal import Decimal, ROUND_HALF_UP

from validate import CENT

TIER1_LIMIT_USD = Decimal("5000000")
TIER1_RATE = Decimal("0.06")
TIER2_RATE = Decimal("0.04")
DUAL_BUYER_SIDE_RATE = Decimal("0.02")
MIN_DEPOSIT_PCT = Decimal("0.05")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def compute_commission(agreed_price, credits_total, dual_agency):
    base = agreed_price - credits_total
    sole = _round2(
        min(base, TIER1_LIMIT_USD) * TIER1_RATE
        + max(base - TIER1_LIMIT_USD, Decimal(0)) * TIER2_RATE
    )
    if dual_agency:
        return _round2(sole + base * DUAL_BUYER_SIDE_RATE)
    return sole


def compute_settlement(agreed_price, credits_total, deposit_amount, commission):
    buyer_due = _round2(agreed_price - credits_total - deposit_amount)
    seller_net = _round2(agreed_price - commission)
    return buyer_due, seller_net


def deposit_minimum(offer_price):
    return _round2(offer_price * MIN_DEPOSIT_PCT)
