"""The append-only adjudication event log (PRD 3.9)."""

from store import db


def append_event(claim, event_type, from_status, to_status, reason_code,
                 actor_role, actor_user_id, pass_number=None):
    row = {
        "_common": False,
        "claim_id": claim["id"],
        "pass_number": claim["adjudication_pass"] if pass_number is None else pass_number,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "reason_code": reason_code,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "occurred_at": db.clock_iso(),
    }
    return db.insert("adjudication_events", row)
