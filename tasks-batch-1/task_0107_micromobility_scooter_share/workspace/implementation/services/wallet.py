"""Wallet ledger helpers (PRD §3.2, §3.5, §3.6).

WalletTransaction is an append-only event log: id + created_at only, no
updated_at / no version (PRD §2.4). Signed amount_cents: positive credits
(TOPUP, TRIP_REFUND, FINE_REFUND), negative debits (TRIP_CHARGE, FINE_CHARGE).
"""
from db import db, stamp_new


def create_txn(rider_id, txn_type, amount_cents, *, trip_id=None, fine_id=None):
    """Append a wallet ledger entry (append-only; not versioned)."""
    txn = {
        "rider_id": rider_id,
        "trip_id": trip_id,
        "fine_id": fine_id,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
    }
    stamp_new(txn, versioned=False)
    db.wallet_transactions[txn["id"]] = txn
    return txn
