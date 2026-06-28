"""System-field management for create / mutate (PRD §2.4, §2.10)."""
from db import store, new_id, _wall_now_iso


def make_full(extra):
    """Create a full-common record (id, created_at, updated_at, version)."""
    ts = _wall_now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(extra)
    return rec


def make_lean(extra):
    """Create a lean-common record (id, created_at only)."""
    rec = {
        "id": new_id(),
        "created_at": _wall_now_iso(),
        "_seq": store.next_seq(),
    }
    rec.update(extra)
    return rec


def bump(record):
    """Refresh updated_at and increment version on a full-common record (PRD §2.4/2.10)."""
    record["updated_at"] = _wall_now_iso()
    record["version"] = record.get("version", 1) + 1
