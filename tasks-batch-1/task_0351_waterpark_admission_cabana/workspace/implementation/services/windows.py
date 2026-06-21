"""EntryWindow derived-field reconciliation and the rain-out cascade.

Kept separate so parks.py (window creation) and routes/windows.py (state machine)
both reuse it without a circular import.
"""
from db import db, touch


def recompute_open_window_count(park):
    """Derived-field reconciliation (PRD §2.7): count OPEN child windows.

    The owning park is mutated: updated_at refreshed, version incremented.
    """
    count = sum(
        1 for w in db.entry_windows.values()
        if w["park_id"] == park["id"] and w["status"] == "OPEN"
    )
    park["open_window_count"] = count
    touch(park)
