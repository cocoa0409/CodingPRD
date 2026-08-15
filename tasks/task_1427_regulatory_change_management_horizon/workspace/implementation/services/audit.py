"""Hash-chained audit trail (PRD §2.9).

One AuditEvent is appended per successful mutating call, for the primary
mutated entity. sequence_number is strictly increasing from 1; the first
event's prev_event_hash is the literal string 'GENESIS'.
"""

from db import fmt_dt, new_id, now_clock, store
from services.calculations import audit_event_hash

GENESIS = "GENESIS"


def append_audit(actor_user_id, actor_role, action, entity_type, entity_id):
    seq = len(store.audit_events) + 1
    prev_hash = store.audit_events[-1]["event_hash"] if store.audit_events else GENESIS
    occurred_at = fmt_dt(now_clock())
    event_hash = audit_event_hash(prev_hash, seq, actor_user_id, action,
                                  entity_type, entity_id, occurred_at)
    event = {
        "id": new_id(),
        "created_at": store.clock,
        "sequence_number": seq,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "occurred_at": occurred_at,
        "prev_event_hash": prev_hash,
        "event_hash": event_hash,
    }
    store.audit_events.append(event)
    return event


def verify_chain():
    """Replay events in sequence order recomputing hashes (PRD §2.9)."""
    prev = GENESIS
    checked = 0
    for event in store.audit_events:
        expected = audit_event_hash(
            prev,
            event["sequence_number"],
            event["actor_user_id"],
            event["action"],
            event["entity_type"],
            event["entity_id"],
            event["occurred_at"],
        )
        checked += 1
        if expected != event["event_hash"] or event["prev_event_hash"] != prev:
            return False, checked
        prev = event["event_hash"]
    return True, checked
