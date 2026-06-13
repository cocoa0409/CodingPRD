"""Record construction, mutation, and shared validation helpers."""
from datetime import datetime, timezone

from db import db, now_iso_ms
from errors import err

# Fields that are internal bookkeeping and must never be serialized out.
_INTERNAL_KEYS = {"_seq", "_visit_logs"}


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
    """Mark a common-fields record as mutated: bump version + updated_at (PRD §2.4)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso_ms(_utcnow())


def serialize(rec):
    """Strip internal keys for output."""
    return {k: v for k, v in rec.items() if k not in _INTERNAL_KEYS}


def sort_by_created(records):
    """Stable sort by creation order (created_at ASC, then insertion seq) — PRD §2.3."""
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


def optional_body(body):
    """Endpoints with no input still tolerate an empty/missing body."""
    if body is None:
        return {}
    if not isinstance(body, dict):
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


def optional_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return value


def require_int(body, name, *, minimum=None, maximum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be <= {maximum}")
    return value


def optional_int(body, name, default, *, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be <= {maximum}")
    return value


def require_number(body, name, *, minimum=None, maximum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be <= {maximum}")
    return float(value)


def require_enum(body, name, allowed):
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return value


def optional_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return value


def require_bool(body, name):
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return value
