"""Record lifecycle helpers: common-field stamping and mutation bumps."""
from db import new_id, now_iso_ms, store


def make_record(extra):
    """Build a record with common system fields (id, created_at, updated_at, version=1)."""
    ts = now_iso_ms()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at, increment version (PRD §2.4)."""
    rec["updated_at"] = now_iso_ms()
    rec["version"] = rec["version"] + 1


def make_payment_txn(reservation_id, kind, amount_cents, note):
    """PaymentTxn is immutable: only id + created_at, no version/updated_at."""
    rec = {
        "id": new_id(),
        "created_at": now_iso_ms(),
        "_seq": store.next_seq(),
        "reservation_id": reservation_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "note": note,
    }
    store.payment_txns[rec["id"]] = rec
    return rec
