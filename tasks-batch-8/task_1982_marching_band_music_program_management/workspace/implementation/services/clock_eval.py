"""Lazy time-driven transitions: OVERDUE for instrument assignments; EXPIRED for arrangements."""
from db import store, now


def apply_time_transitions():
    """Evaluate clock-driven transitions. Called on clock set and on reads."""
    n = now()
    for a in store.instrument_assignments.values():
        if a["status"] == "ACTIVE" and a.get("due_date") and n > a["due_date"]:
            a["status"] = "OVERDUE"
            a["version"] += 1
            from db import now_iso
            a["updated_at"] = now_iso()
    for arr in store.arrangements.values():
        if arr["status"] == "LICENSED_ACTIVE" and arr.get("rights_end") and n > arr["rights_end"]:
            arr["status"] = "EXPIRED"
            arr["version"] += 1
            from db import now_iso
            arr["updated_at"] = now_iso()
