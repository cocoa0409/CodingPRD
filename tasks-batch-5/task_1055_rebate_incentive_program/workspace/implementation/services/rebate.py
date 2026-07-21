"""Rebate pricing (PRD §3.5) and payout amount settlement (PRD §3.8)."""
from decimal import Decimal

import db


def included_receipts(claim, variant):
    rs = db.receipts_of_claim(claim["id"])
    if variant == "final":
        rs = [r for r in rs if r["validated"]]
    return rs


def total_units(receipt_list):
    return sum(
        line["quantity"] for r in receipt_list for line in r["lines"]
    )


def select_pct(claimant, offer, units):
    if claimant["type"] == "DEALER":
        if not offer["dealer_tier_enabled"]:
            return db.DEALER_TIER_1_PCT
        if units <= db.DEALER_TIER_1_MAX_UNITS:
            return db.DEALER_TIER_1_PCT
        if units <= db.DEALER_TIER_2_MAX_UNITS:
            return db.DEALER_TIER_2_PCT
        return db.DEALER_TIER_3_PCT
    return db.CONSUMER_REBATE_PCT


def compute(claim, claimant, offer, variant):
    """The five pinned steps of PRD §3.5. Returns (rebate_cents, total_units)."""
    included = included_receipts(claim, variant)
    units = total_units(included)
    pct = select_pct(claimant, offer, units)

    raw = 0
    for r in included:  # already ordered by created_at ASC
        for line in r["lines"]:  # submitted array order
            raw += db.round_half_up(
                Decimal(line["quantity"]) * Decimal(line["unit_price_cents"]) * pct
            )

    if claimant["type"] == "CONSUMER" and raw > 0:
        raw += db.CONSUMER_FLAT_BONUS_CENTS

    return min(raw, offer["max_rebate_cents_per_claim"]), units


def settle_payout_amounts(claim, claimant, requested_method):
    """PRD §3.8 - pinned order: gross, then method from gross, then fee, then net."""
    gross = claim["final_rebate_cents"] or 0
    if requested_method is not None:
        method = requested_method
    elif claimant["type"] == "CONSUMER" and gross >= db.CARD_METHOD_MIN_CENTS:
        method = "VIRTUAL_CARD"
    else:
        method = "CHECK"
    fee = db.CHECK_FEE_CENTS if method == "CHECK" else db.CARD_FEE_CENTS
    net = gross - fee
    return gross, method, fee, net
