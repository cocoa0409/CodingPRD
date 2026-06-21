"""LedgerEntry postings and customer-balance derivation (PRD §2.9).

Sign convention (fixed):
  DEPOSIT_HOLD    = +deposit  (held)
  DEPOSIT_RELEASE = -refund_portion (negative magnitude)
  DEPOSIT_CAPTURE = -applied_from_deposit (negative magnitude)
  FEE_CHARGE      = +fee  (customer owes)
  FEE_WAIVE       = -waiver_credit (negative magnitude)

Derived balances:
  deposit_held_cents = sum(DEPOSIT_HOLD) - |sum(DEPOSIT_RELEASE)| - |sum(DEPOSIT_CAPTURE)|
  balance_owed_cents = sum(FEE_CHARGE) - |sum(FEE_WAIVE)|
"""
import db


def post(customer_id, entry_type, amount_cents, reservation_id=None):
    entry = {
        "customer_id": customer_id,
        "reservation_id": reservation_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
    }
    db.stamp_create_ledger(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry


def _entries_for_customer(customer_id):
    return [e for e in db.ledger_entries.values() if e["customer_id"] == customer_id]


def deposit_held_for_customer(customer_id):
    total = 0
    for e in _entries_for_customer(customer_id):
        if e["entry_type"] == "DEPOSIT_HOLD":
            total += e["amount_cents"]
        elif e["entry_type"] in ("DEPOSIT_RELEASE", "DEPOSIT_CAPTURE"):
            total -= abs(e["amount_cents"])
    return total


def balance_owed_for_customer(customer_id):
    total = 0
    for e in _entries_for_customer(customer_id):
        if e["entry_type"] == "FEE_CHARGE":
            total += e["amount_cents"]
        elif e["entry_type"] == "FEE_WAIVE":
            total -= abs(e["amount_cents"])
    return total
