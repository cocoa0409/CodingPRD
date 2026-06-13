"""Low-level store mutations: timestamp/version bumps and append-only ledger writes.

PRD §2.9: whenever an operation changes a resource, its updated_at is refreshed and
its version is incremented by one (this includes derived-field refreshes such as a
card whose balance changed or a slot whose reserved_count changed).
"""
from db import db, new_id, iso_now


def touch(entity):
    """Refresh updated_at and bump version by one on a mutable entity."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity["version"] + 1


def append_wallet_txn(card_id, kind, amount_cents, order_id=None):
    txn = {
        "id": new_id(),
        "created_at": iso_now(),
        "_seq": db.next_seq(),
        "card_id": card_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "order_id": order_id,
    }
    db.wallet_transactions[txn["id"]] = txn
    return txn


def append_star_ledger(member_id, kind, delta_stars, order_id=None):
    entry = {
        "id": new_id(),
        "created_at": iso_now(),
        "_seq": db.next_seq(),
        "member_id": member_id,
        "kind": kind,
        "delta_stars": delta_stars,
        "order_id": order_id,
    }
    db.star_ledger_entries[entry["id"]] = entry
    return entry
