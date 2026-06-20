"""Chain-of-custody helpers (PRD §3.5)."""

from db import db, new_id, next_seq, now_iso

CUSTODY_STEPS = {"COLLECT", "SEAL", "SHIP", "LAB_RECEIVE", "LAB_REPORT", "MRO_RECEIVE"}

# Canonical pre-lab sequence used to validate custody ordering for COLLECT..LAB_RECEIVE.
CANONICAL_PREFIX = ["COLLECT", "SEAL", "SHIP", "LAB_RECEIVE"]


def events_for(drug_screen_id):
    """All custody events for a screen, in seq order."""
    evts = [e for e in db.custody_events.values()
            if e["drug_screen_id"] == drug_screen_id]
    return sorted(evts, key=lambda e: e["seq"])


def active_events_for(drug_screen_id):
    """Custody events recorded in the current collection cycle (after the last
    recollection reset). Used to validate the canonical prefix per cycle."""
    cycle = db.drug_screens[drug_screen_id].get("_custody_cycle", 0)
    evts = [e for e in db.custody_events.values()
            if e["drug_screen_id"] == drug_screen_id and e.get("_cycle", 0) == cycle]
    return sorted(evts, key=lambda e: e["seq"])


def append_event(drug_screen, step, actor_user_id, note=None):
    """Append a custody event with the next per-screen seq index."""
    existing = events_for(drug_screen["id"])
    next_index = (max((e["seq"] for e in existing), default=0)) + 1
    evt = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq_create": next_seq(),
        "drug_screen_id": drug_screen["id"],
        "step": step,
        "actor_user_id": actor_user_id,
        "seq": next_index,
        "note": note,
        "_cycle": drug_screen.get("_custody_cycle", 0),
    }
    db.custody_events[evt["id"]] = evt
    return evt
