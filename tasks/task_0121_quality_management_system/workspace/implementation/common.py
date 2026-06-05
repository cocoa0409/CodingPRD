"""Common resource property helpers and shared utilities (PRD 2.4)."""
from datetime import datetime, timezone

from db import new_id
from errors import ERR_INVALID_REQUEST, err
from response import now_iso


def stamp_create(record, with_version=True):
    """Attach common create fields. id + created_at always; updated_at + version
    for all entities except the append-only EightDStep (PRD 2.4)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on any mutation (PRD 2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST on
    a malformed value."""
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, "Invalid datetime")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "Invalid %s: %r" % (field, value))


def require_non_negative_int(value, field, minimum=0):
    if not isinstance(value, int) or isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if value < minimum:
        raise err(ERR_INVALID_REQUEST, "%s must be >= %d" % (field, minimum))
    return value


def require_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, "%s must be a non-empty string" % field)
    return value
