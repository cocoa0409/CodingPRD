"""Append-only ledger writes + derived balance reconciliation.

- CreditLedgerEntry -> membership.credit_balance = sum(delta)   (PRD §2.9)
- Payment(source=GIFT_CARD) -> gift_card.remaining_balance_cents = initial - sum(amount)
  with status -> DEPLETED at 0.                                  (PRD §2.9)
"""
from db import db, stamp_ledger


def add_credit_entry(membership, reason, delta, booking_id=None):
    entry = {
        "membership_id": membership["id"],
        "booking_id": booking_id,
        "reason": reason,
        "delta": delta,
    }
    stamp_ledger(entry)
    db.credit_ledger[entry["id"]] = entry
    reconcile_credit_balance(membership)
    return entry


def reconcile_credit_balance(membership):
    total = sum(
        e["delta"]
        for e in db.credit_ledger.values()
        if e["membership_id"] == membership["id"]
    )
    membership["credit_balance"] = total
    return total


def add_payment(kind, source, amount_cents, booking_id=None, gift_card_id=None):
    payment = {
        "booking_id": booking_id,
        "gift_card_id": gift_card_id,
        "kind": kind,
        "source": source,
        "amount_cents": amount_cents,
    }
    stamp_ledger(payment)
    db.payments[payment["id"]] = payment
    if source == "GIFT_CARD" and gift_card_id is not None:
        card = db.gift_cards.get(gift_card_id)
        if card is not None:
            reconcile_gift_card_balance(card)
    return payment


def reconcile_gift_card_balance(card):
    spent = sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["source"] == "GIFT_CARD" and p["gift_card_id"] == card["id"]
    )
    remaining = card["initial_balance_cents"] - spent
    if remaining < 0:
        remaining = 0
    card["remaining_balance_cents"] = remaining
    # status -> DEPLETED at 0; never auto-revives a VOID card.
    if card["status"] == "ACTIVE" and remaining == 0:
        card["status"] = "DEPLETED"
    elif card["status"] == "DEPLETED" and remaining > 0:
        # A refund (negative payment) can restore balance, reviving the card.
        card["status"] = "ACTIVE"
    return remaining
