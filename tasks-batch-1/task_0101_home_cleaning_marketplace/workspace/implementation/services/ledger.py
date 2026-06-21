"""Ledger entries and wallet interplay per PRD §2.8-2.9, §3.3.

A LedgerEntry is append-only (id + created_at only). amount_cents is signed:
positive credits the customer, negative debits. The customer's
wallet_credit_cents is constrained never to drop below zero.

Charge semantics (PRD §3.3): the customer's wallet is drawn down first
against the quoted amount; any remainder is "accrued against the customer".
Since wallet can't go negative, a charge reduces wallet by min(wallet, amount).
"""
import db


def write_entry(customer_id, kind, amount_cents, booking_id=None):
    """Create an append-only LedgerEntry."""
    rec = {
        "customer_id": customer_id,
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    return db.insert(db.ledger_entries, rec, append_only=True)


def charge_customer(customer, amount_cents, booking_id):
    """Record a CHARGE and draw down the wallet first (remainder accrues).

    Returns the ledger entry. amount_cents is the positive charge magnitude;
    the entry stores it as a negative (debit) signed amount.
    """
    drawn = min(customer.get("wallet_credit_cents", 0), amount_cents)
    customer["wallet_credit_cents"] = customer.get("wallet_credit_cents", 0) - drawn
    db.touch(customer)
    return write_entry(customer["id"], "CHARGE", -amount_cents, booking_id)


def refund_customer(customer, amount_cents, booking_id):
    """Record a REFUND crediting the wallet (positive signed amount)."""
    customer["wallet_credit_cents"] = customer.get("wallet_credit_cents", 0) + amount_cents
    db.touch(customer)
    return write_entry(customer["id"], "REFUND", amount_cents, booking_id)


def change_fee(customer, fee_cents, booking_id):
    """Record a CHANGE_FEE debiting the customer (negative signed amount).

    Drawn against the wallet first; never below zero.
    """
    drawn = min(customer.get("wallet_credit_cents", 0), fee_cents)
    customer["wallet_credit_cents"] = customer.get("wallet_credit_cents", 0) - drawn
    db.touch(customer)
    return write_entry(customer["id"], "CHANGE_FEE", -fee_cents, booking_id)


def reclean_credit(customer, booking_id):
    """Record a zero-valued RECLEAN_CREDIT marker; no balance movement."""
    return write_entry(customer["id"], "RECLEAN_CREDIT", 0, booking_id)
