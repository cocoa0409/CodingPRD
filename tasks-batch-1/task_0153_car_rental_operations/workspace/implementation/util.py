"""Shared helpers: datetime parsing, timestamps, record stamping, validation."""
import math
from datetime import datetime, timezone

import db
from errors import err


def parse_iso8601(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST on
    anything unparseable. Naive timestamps are treated as UTC.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "expected an ISO 8601 datetime string")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid ISO 8601 datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_new(record):
    """Apply id + created_at + updated_at + version to a full entity."""
    record["id"] = db.new_id()
    ts = db.now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_audit(record):
    """Apply id + created_at to an append-only audit record (no version/updated_at)."""
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Bump updated_at and version on a mutation of a full entity."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 1) + 1


# ---- request body field validation (ERR_INVALID_REQUEST, priority 4) -----


def require(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    value = require(body, field)
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "field %s must be a non-empty string" % field)
    return value


def require_int(body, field, minimum=None):
    value = require(body, field)
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "field %s must be >= %s" % (field, minimum))
    return value


def optional_int(body, field, default=None, minimum=None):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "field %s must be >= %s" % (field, minimum))
    return value


def optional_bool(body, field, default=False):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "field %s must be a boolean" % field)
    return value


def require_int_in_range(body, field, low, high):
    value = require_int(body, field)
    if value < low or value > high:
        raise err(
            "ERR_INVALID_REQUEST",
            "field %s must be between %s and %s" % (field, low, high),
        )
    return value


def optional_int_in_range(body, field, low, high, default):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % field)
    if value < low or value > high:
        raise err(
            "ERR_INVALID_REQUEST",
            "field %s must be between %s and %s" % (field, low, high),
        )
    return value


def require_enum(body, field, allowed):
    value = require(body, field)
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "field %s must be one of %s" % (field, allowed))
    return value
