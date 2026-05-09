"""SyncEvent helpers — emit / lookup latest by type & subject (PRD §2.6)."""
from db import db, new_id, now_iso


def emit_sync_event(*, program_id: str, event_type: str, subject_type: str,
                    subject_id: str, payload: dict | None,
                    current_period_index: int) -> dict:
    """Append a new SyncEvent (only id + created_at + system fields)."""
    event = {
        "id": new_id(),
        "created_at": now_iso(),
        "housing_program_id": program_id,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload or {},
        "emitted_period": int(current_period_index),
    }
    db.sync_events[event["id"]] = event
    db.sync_event_order.append(event["id"])
    return event


def latest_event(*, event_type: str, subject_id: str) -> dict | None:
    """Return the most-recently-emitted SyncEvent of given type for subject_id,
    or None if no such event exists. Iteration walks insertion order in reverse.
    """
    for eid in reversed(db.sync_event_order):
        e = db.sync_events.get(eid)
        if not e:
            continue
        if e.get("event_type") == event_type and e.get("subject_id") == subject_id:
            return e
    return None


def emit_audit_eligibility_change(*, program_id: str, subject_type: str,
                                  subject_id: str, actor_user_id: str,
                                  before, after, note: str,
                                  current_period_index: int) -> dict:
    return emit_sync_event(
        program_id=program_id,
        event_type="AUDIT_ELIGIBILITY_CHANGE",
        subject_type=subject_type,
        subject_id=subject_id,
        payload={
            "actor_user_id": actor_user_id,
            "before": before,
            "after": after,
            "note": note,
        },
        current_period_index=current_period_index,
    )


def emit_audit_allocation_decision(*, program_id: str, subject_type: str,
                                   subject_id: str, actor_user_id: str,
                                   before, after, note: str,
                                   current_period_index: int) -> dict:
    return emit_sync_event(
        program_id=program_id,
        event_type="AUDIT_ALLOCATION_DECISION",
        subject_type=subject_type,
        subject_id=subject_id,
        payload={
            "actor_user_id": actor_user_id,
            "before": before,
            "after": after,
            "note": note,
        },
        current_period_index=current_period_index,
    )
