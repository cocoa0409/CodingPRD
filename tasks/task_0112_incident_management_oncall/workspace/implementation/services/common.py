"""Shared entity helpers: common-field stamping, validation, parsing."""
from datetime import datetime, timezone

from db import db, new_id, iso_ms, next_seq
from errors import ApiError


def stamp_create(record, common_fields=True):
    """Set id + created_at + insertion seq; non-log entities also get
    updated_at + version=1."""
    now = db.clock.now()
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = next_seq()
    if common_fields:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Mutation: refresh updated_at and bump version by exactly 1."""
    record["updated_at"] = db.clock.now()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Field validation (priority 4: ERR_INVALID_REQUEST, 422)
# ---------------------------------------------------------------------------

def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a non-empty string.")
    return val


def optional_str(body, field):
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be a string.")
    return val


def require_int(body, field, minimum=None, allow_bool=False):
    val = body.get(field)
    if isinstance(val, bool) and not allow_bool:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer.")
    if not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an integer.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}.")
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}.")
    return val


def require_enum(body, field, members):
    val = body.get(field)
    if not isinstance(val, str) or val not in members:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(members)}.")
    return val


def optional_enum(body, field, members, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in members:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(members)}.")
    return val


def parse_datetime(body, field, required=True):
    """Parse an ISO 8601 datetime field -> aware UTC datetime.

    Bad/missing -> ERR_INVALID_REQUEST (priority 4).
    """
    val = body.get(field)
    if val is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' is required.")
        return None
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO 8601 string.")
    dt = parse_iso(val)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' is not a valid ISO 8601 datetime.")
    return dt


def parse_iso(val):
    """Parse an ISO 8601 string to an aware UTC datetime, or None on failure."""
    if not isinstance(val, str):
        return None
    s = val.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
