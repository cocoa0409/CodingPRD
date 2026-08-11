"""Buyer credit: effective limit and live exposure (PRD 3.7)."""
import config
from money import D, q2
from store import db

OPEN_PURCHASE_STATUSES = ("CONFIRMED", "INVOICED", "ADJUSTED")

_MULTIPLIER = {
    "BONDED": config.BONDED_LIMIT_MULTIPLIER,
    "UNSECURED": config.UNSECURED_LIMIT_MULTIPLIER,
    "CASH_ONLY": config.CASH_ONLY_LIMIT_MULTIPLIER,
}


def effective_limit(reg):
    """credit_limit * bond multiplier + cash deposit + override."""
    multiplier = _MULTIPLIER[reg["bond_type"]]
    return q2(D(reg["credit_limit"]) * multiplier
              + D(reg["cash_deposit_amount"])
              + D(reg["override_limit"]))


def open_purchase_amount(reg_id):
    total = D(0)
    for purchase in db["purchases"].values():
        if purchase["buyer_registration_id"] != reg_id:
            continue
        if purchase["status"] not in OPEN_PURCHASE_STATUSES:
            continue
        total += D(purchase["extended_amount"])
    return q2(total)


def winning_bid_amount(reg_id):
    total = D(0)
    for bid in db["bids"].values():
        if bid["buyer_registration_id"] != reg_id:
            continue
        if bid["status"] != "WINNING":
            continue
        total += D(bid["projected_extension"])
    return q2(total)


def exposure(reg):
    return q2(open_purchase_amount(reg["id"]) + winning_bid_amount(reg["id"])
              - D(reg["payments_applied"]))


def available_credit(reg):
    return q2(D(reg["effective_limit"]) - exposure(reg))
