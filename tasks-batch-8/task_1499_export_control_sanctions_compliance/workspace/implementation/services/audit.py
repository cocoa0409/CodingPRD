"""Audit record writing and retention purge (calculation audit_retention)."""

from datetime import timedelta

import db

RETENTION_DAYS = 1825


def write_audit(event_type, entity_type, entity_id, actor_role, actor_user_id, detail):
    """AuditRecord carries only id + created_at (no updated_at / version)."""
    created = db.now_dt()
    retain_dt = created + timedelta(days=RETENTION_DAYS)
    record = {
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "detail": detail,
        "retain_until": db.fmt_dt(retain_dt),
    }
    record["id"] = db.new_id()
    record["created_at"] = db.fmt_dt(created)
    record["_created_dt"] = created
    record["_retain_dt"] = retain_dt
    record["_seq"] = db.next_seq()
    db.AUDIT_RECORDS[record["id"]] = record
    return record


def purge_expired():
    """Delete records with retain_until STRICTLY before the current clock."""
    now = db.now_dt()
    doomed = [rid for rid, r in db.AUDIT_RECORDS.items() if r["_retain_dt"] < now]
    for rid in doomed:
        del db.AUDIT_RECORDS[rid]
    return len(doomed)
