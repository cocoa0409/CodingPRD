"""Derived-balance projections via event replay (PRD §2.5).

Card balance = sum of WalletTransaction.amount_cents over the card's txns.
Star balance = sum of delta_stars over all the member's ledger entries.
Lifetime stars = sum of delta_stars over EARN entries only (monotone non-decreasing).
Tier = GOLD when lifetime_stars >= GOLD_THRESHOLD (200) else GREEN.
"""
from db import db
from constants import GOLD_THRESHOLD


def card_balance_cents(card_id):
    total = 0
    for txn in db.wallet_transactions.values():
        if txn["card_id"] == card_id:
            total += txn["amount_cents"]
    return total


def card_for_member(member_id):
    for card in db.cards.values():
        if card["member_id"] == member_id:
            return card
    return None


def star_balance(member_id):
    total = 0
    for e in db.star_ledger_entries.values():
        if e["member_id"] == member_id:
            total += e["delta_stars"]
    return total


def lifetime_stars(member_id):
    total = 0
    for e in db.star_ledger_entries.values():
        if e["member_id"] == member_id and e["kind"] == "EARN":
            total += e["delta_stars"]
    return total


def tier_for(lifetime):
    return "GOLD" if lifetime >= GOLD_THRESHOLD else "GREEN"


def slot_reserved_count(slot_id):
    """Count Orders against the slot whose fulfillment_status is in the reserved set."""
    reserved_states = ("PLACED", "IN_PREP", "READY")
    count = 0
    for o in db.orders.values():
        if o["pickup_slot_id"] == slot_id and o["fulfillment_status"] in reserved_states:
            count += 1
    return count
