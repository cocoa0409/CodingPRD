"""Record construction, mutation, and shared validation helpers."""
from datetime import datetime, timezone

from db import db, now_iso_ms
from errors import err

# Fields that are internal bookkeeping and must never be serialized out.
_INTERNAL_KEYS = {"_seq"}


def _utcnow():
    return datetime.now(timezone.utc)


def new_record(fields, *, common=True):
    """Create a record dict with id/created_at (+ updated_at/version when common).

    `fields` are the entity-specific fields. Returns the stored dict (caller
    inserts it into the appropriate collection).
    """
    rec = dict(fields)
    rec["id"] = db.new_id()
    ts = now_iso_ms(_utcnow())
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a common-fields record as mutated: bump version + updated_at."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso_ms(_utcnow())


def serialize(rec):
    """Strip internal keys for output."""
    return {k: v for k, v in rec.items() if k not in _INTERNAL_KEYS}


def sort_by_created(records):
    """Stable sort by creation order (created_at ASC, then insertion seq)."""
    return sorted(records, key=lambda r: r["_seq"])


def paginate(params):
    """Extract and validate limit/offset (PRD §2.3). Returns (limit, offset)."""
    limit = params.get("limit")
    offset = params.get("offset")
    if limit is None:
        limit = 10
    else:
        limit = _parse_int(limit, "limit")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range")
    if offset is None:
        offset = 0
    else:
        offset = _parse_int(offset, "offset")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset out of range")
    return limit, offset


def _parse_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")


def require_json_object(body):
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return value


def require_int(body, name, *, minimum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    return value
