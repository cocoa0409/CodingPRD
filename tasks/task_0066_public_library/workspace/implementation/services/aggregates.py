"""Title/copy aggregates and BookTitle status recomputation."""
import db
from clock import iso, now


def _live_copies_for_title(book_title_id: str):
    return [c for c in db.copies.values() if c["book_title_id"] == book_title_id]


def recompute_title_aggregates(book_title_id: str):
    """Recompute total_copies / available_copies / status on a BookTitle.

    total_copies counts ALL copies (any status, including WEEDED).
    available_copies counts copies with status == AVAILABLE.
    BookTitle.status transitions to WITHDRAWN if all copies are WEEDED
    AND there's at least one copy.
    """
    bt = db.book_titles.get(book_title_id)
    if not bt:
        return
    all_copies = _live_copies_for_title(book_title_id)
    total = len(all_copies)
    available = sum(1 for c in all_copies if c["status"] == "AVAILABLE")
    changed = False
    if bt.get("total_copies") != total:
        bt["total_copies"] = total
        changed = True
    if bt.get("available_copies") != available:
        bt["available_copies"] = available
        changed = True
    # Title -> WITHDRAWN cascade only when there exists at least one copy and all are WEEDED.
    if total > 0 and all(c["status"] == "WEEDED" for c in all_copies):
        if bt.get("status") != "WITHDRAWN":
            bt["status"] = "WITHDRAWN"
            changed = True
    if changed:
        bt["updated_at"] = iso(now())
        bt["version"] = bt.get("version", 1) + 1
