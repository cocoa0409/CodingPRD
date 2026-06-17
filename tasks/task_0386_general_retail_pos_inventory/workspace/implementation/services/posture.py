"""Store posture derivation (PRD §2.8, calc G)."""


def open_session_for_store(db, store_id):
    """Return the single OPEN CashDrawerSession for the store, or None."""
    for s in db.cash_sessions.values():
        if s["store_id"] == store_id and s["status"] == "OPEN":
            return s
    return None


def posture_for_store(db, store_id):
    """PRD §2.8: DRAWER_OPEN when exactly one session is OPEN, else LOCKED."""
    open_count = sum(
        1 for s in db.cash_sessions.values()
        if s["store_id"] == store_id and s["status"] == "OPEN"
    )
    return "DRAWER_OPEN" if open_count == 1 else "LOCKED"


def store_view(db, store):
    """Serialize a store with its derived posture (PRD §2.8)."""
    from common import public_view
    out = public_view(store)
    out["posture"] = posture_for_store(db, store["id"])
    return out
