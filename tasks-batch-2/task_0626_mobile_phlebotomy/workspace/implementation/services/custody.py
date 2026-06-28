"""Chain-of-custody append helper (PRD 3.7).

A ChainOfCustodyEvent is append-only and immutable: id + created_at only. It records
specimen_id, prior_event_id (null for the first), event_type, actor_role from
X-User-Role, actor_user_id from X-User-ID, and a zero-based sequence_index.
"""
from db import db, new_id, now_iso


def chain_for_specimen(specimen_id):
    """Return the specimen's custody events sorted by sequence_index."""
    evts = [e for e in db.custody_events.values() if e["specimen_id"] == specimen_id]
    return sorted(evts, key=lambda e: e["sequence_index"])


def append_event(specimen_id, event_type, actor_role, actor_user_id):
    """Append a custody event, auto-linking prior_event_id and sequence_index."""
    chain = chain_for_specimen(specimen_id)
    if chain:
        prior = chain[-1]
        prior_event_id = prior["id"]
        sequence_index = prior["sequence_index"] + 1
    else:
        prior_event_id = None
        sequence_index = 0

    event = {
        "id": new_id(),
        "created_at": now_iso(),
        "specimen_id": specimen_id,
        "prior_event_id": prior_event_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "sequence_index": sequence_index,
    }
    db.custody_events[event["id"]] = event
    return event
