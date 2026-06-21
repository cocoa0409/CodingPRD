"""Shared store lookup, audit, and pagination helpers."""
import db
from errors import err


def get_or_404(table, resource_id):
    """Fetch a record by id or raise ERR_NOT_FOUND (PRD §2.5)."""
    record = table.get(resource_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return record


def append_audit(subject_type, subject_id, action, actor_role, actor_user_id):
    """Append an AuditEvent (PRD §3.12). Light entity: id + created_at only."""
    record = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
    }
    db.stamp_create(record, with_version=False)
    db.audit_events.append(record)
    return record


def sorted_by_created(records):
    """Sort by created_at ascending (PRD §2.3). A monotonic creation sequence
    breaks ties so records minted within the same millisecond keep true order."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(records, limit, offset):
    """Apply offset/limit to an already-sorted list; return (page, total)."""
    total = len(records)
    page = records[offset: offset + limit]
    return page, total
