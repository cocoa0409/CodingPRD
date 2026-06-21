"""Account ledger and computed account fields (PRD §2.9, §3.x).

The account's outstanding_balance_cents is never stored as a mutable number; it
is a full recompute over the account's AccountLedgerEntry rows (signed sum) in
created_at ASC order. AccountLedgerEntry carries only id/created_at (append-only,
no updated_at/version — PRD §2.4).
"""
from db import DB

from .common import new_record, sort_by_created

# entry_type values that increase the balance vs decrease it (PRD §2.9).
POSITIVE_TYPES = {
    "DEPOSIT_HOLD", "RENTAL_CHARGE", "FUEL_CHARGE",
    "CLEANING_CHARGE", "LATE_FEE", "DAMAGE_CHARGE",
}
NEGATIVE_TYPES = {"DEPOSIT_REFUND", "PAYMENT"}

OPEN_RESERVATION_STATES = {"CONFIRMED", "DISPATCHED_DELIVERY", "PICKED_UP", "ON_RENT"}


def post_entry(account_id, entry_type, amount_cents, rental_agreement_id=None):
    """Append an AccountLedgerEntry (PRD §2.9). Returns the entry."""
    entry = new_record({
        "contractor_account_id": account_id,
        "rental_agreement_id": rental_agreement_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
    }, full_common=False)
    DB.ledger_entries[entry["id"]] = entry
    return entry


def entries_for_account(account_id):
    return [e for e in DB.ledger_entries.values()
            if e["contractor_account_id"] == account_id]


def recompute_balance(account_id):
    """Full signed recompute over ALL ledger entries for the account (PRD §2.9)."""
    rows = sort_by_created(entries_for_account(account_id))
    return sum(e["amount_cents"] for e in rows)


def open_reservation_count(account_id):
    """Count account reservations in an open state (PRD §2.9)."""
    return sum(
        1 for r in DB.reservations.values()
        if r["contractor_account_id"] == account_id
        and r["reservation_state"] in OPEN_RESERVATION_STATES
    )


def account_view(account):
    """Account record with freshly recomputed computed fields (PRD §3.3, §2.9)."""
    out = dict(account)
    out["outstanding_balance_cents"] = recompute_balance(account["id"])
    out["open_reservation_count"] = open_reservation_count(account["id"])
    return out
