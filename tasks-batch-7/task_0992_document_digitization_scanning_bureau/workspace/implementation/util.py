"""Shared helpers: id generation, timestamps, validation utilities."""

import uuid
from datetime import datetime, timezone

from db import db
from errors import ApiError, ERR_INVALID_REQUEST


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical clock time."""
    return db.current_utc


def now_iso():
    from response import iso_ts

    return iso_ts(db.current_utc)


def bump(entity):
    """Refresh updated_at and increment version on a mutable entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def make_entity(fields):
    """Create a new entity dict with common fields."""
    ts = now_iso()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    e.update(fields)
    return e


def make_event(fields):
    """Create an append-only event row (id + created_at only)."""
    db.seq += 1
    e = {"id": new_id(), "created_at": now_iso(), "_seq": db.seq}
    e.update(fields)
    return e


def get_body():
    """Parse JSON request body; must be an object if present."""
    from flask import request

    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be valid JSON", 400)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def require_fields(body, fields):
    """Ensure required fields are present and non-null."""
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def reject_unknown(body, allowed):
    """Reject unknown or server-computed keys in the payload."""
    for k in body:
        if k not in allowed:
            raise ApiError(ERR_INVALID_REQUEST, f"Unknown field: {k}", 400)


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a boolean", 400)
    return v


def as_int(v, name, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be an integer", 400)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}", 400)
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be <= {maximum}", 400)
    return v


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string", 400)
    return v


def as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be a number", 400)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}", 400
        )
    return v


def parse_iso8601(v, name):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 string", 400)
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {name} is not valid ISO 8601", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
