"""LedgerEntry factory — enforces the append-only shape from §2.6."""
import db
from services import balance


def post_entry(*, member_id: str, entry_kind: str, delta_minutes: int,
               exchange_id: str = None, redemption_id: str = None,
               memo: str = None) -> dict:
    """Insert a LedgerEntry. LedgerEntry has NO updated_at / version (§2.4)."""
    entry = {
        "id": db.new_id(),
        "member_id": member_id,
        "exchange_id": exchange_id,
        "redemption_id": redemption_id,
        "entry_kind": entry_kind,
        "delta_minutes": int(delta_minutes),
        "posted_at": db.get_clock_iso(),
        "memo": memo,
        "created_at": db._now_wall_iso(),
        "_seq": db.next_seq(),
    }
    db.ledger_entries[entry["id"]] = entry
    return entry
