"""Entity construction, common-field management, and serialization."""
from clock import iso8601
from db import db


def now():
    return db.clock.now()


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity (PRD §2.4)."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1


def make_common(entity_id=None, with_version=True):
    ts = now()
    base = {
        "id": entity_id or db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        base["updated_at"] = ts
        base["version"] = 1
    return base


# ---- Serialization ----------------------------------------------------------

_DATETIME_FIELDS = {
    "created_at", "updated_at", "start_date", "end_date", "period_start",
    "period_end", "due_date", "coverage_start", "coverage_end",
    "notice_sent_date", "lien_filed_date", "scheduled_sale_date",
}


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in _DATETIME_FIELDS:
            out[k] = iso8601(v) if v is not None else None
        else:
            out[k] = v
    return out
