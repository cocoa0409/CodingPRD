"""Common helpers: timestamps, version bumps, audit/outbox writers."""
from clock import now
from db import store, new_id


def stamp_create(row: dict, common_fields: bool = True) -> dict:
    """Apply system-managed fields on creation. Mutates and returns row."""
    t = now()
    if "id" not in row:
        row["id"] = new_id()
    row.setdefault("created_at", t)
    if common_fields:
        row.setdefault("updated_at", t)
        row.setdefault("version", 0)
    return row


def bump(row: dict) -> dict:
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def write_audit(subject_kind: str, subject_id: str, action: str,
                actor_role: str, actor_id: str,
                from_state=None, to_state=None, payload=None) -> dict:
    row = {
        "id": new_id(),
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "from_state": from_state,
        "to_state": to_state,
        "payload": payload or {},
        "created_at": now(),
    }
    store.audit_events[row["id"]] = row
    return row


def emit_event(target_system: str, event_name: str, subject_kind: str,
               subject_id: str, payload: dict = None) -> dict:
    key = (subject_kind, subject_id)
    store.outbox_seq[key] += 1
    seq = store.outbox_seq[key]
    t = now()
    row = {
        "id": new_id(),
        "target_system": target_system,
        "event_name": event_name,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "payload": payload or {},
        "sequence": seq,
        "emitted_at": t,
        "created_at": t,
    }
    store.system_events[row["id"]] = row
    return row


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total


def parse_pagination(args):
    """Parse limit/offset from request args; raise ERR_VALIDATION if invalid."""
    from errors import E, raise_error
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise_error(E.VALIDATION, "limit must be integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_error(E.VALIDATION, "offset must be integer")
    if limit < 1 or limit > 100:
        raise_error(E.VALIDATION, "limit out of range")
    if offset < 0:
        raise_error(E.VALIDATION, "offset must be >= 0")
    return limit, offset


def check_version_occ(row: dict, body: dict):
    from errors import E, raise_error
    if body is None:
        return
    if "version" in body and body["version"] is not None:
        if body["version"] != row.get("version", 0):
            raise_error(E.VERSION_CONFLICT, "version mismatch")


def sort_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at"), r.get("id")))
