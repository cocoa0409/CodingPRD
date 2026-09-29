"""Append-only transparency log (PRD 2.12)."""
import db


def append(election_rec, event_type, actor_role, actor_user_id, subject_entity,
           subject_id, summary):
    election_id = election_rec["id"] if election_rec else None
    sequence = 1 + sum(
        1 for e in db.transparency_log.values() if e["election_id"] == election_id
    )
    return db.make_record(
        db.transparency_log,
        {
            "election_id": election_id,
            "sequence": sequence,
            "event_type": event_type,
            "actor_role": actor_role,
            "actor_user_id": actor_user_id,
            "subject_entity": subject_entity,
            "subject_id": subject_id,
            "ballot_content_disclosed": False,
            "summary": summary,
            "recorded_at": db.now(),
        },
        common=False,
    )
