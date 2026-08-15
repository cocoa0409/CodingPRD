"""Shared helpers: payload validation, timestamp parsing, entity stamping."""

from datetime import datetime, timezone

import errors
from db import new_id, iso_from_dt
import clock


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 timestamp string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def truncate_minute(dt):
    """Truncate to whole-minute UTC (never round up) per PRD 2.6."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(second=0, microsecond=0)


def iso_minute(dt):
    """ISO 8601 UTC at minute precision (seconds zeroed)."""
    dt = truncate_minute(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def logical_now_iso():
    """Current logical time in the standard 3-fractional-digit format."""
    return iso_from_dt(clock.now())


def get_json_body():
    from flask import request
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_field(body, field):
    val = body.get(field)
    if val is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return val


def require_int(body, field):
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"{field} must be an integer")
    return val


def optional_int(body, field):
    val = body.get(field)
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"{field} must be an integer")
    return val


def require_enum(body, field, allowed):
    val = require_field(body, field)
    if val not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}")
    return val


def new_entity(extra=None):
    """Common fields per PRD 2.4: id, created_at, updated_at, version."""
    now_iso = logical_now_iso()
    ent = {
        "id": new_id(),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    if extra:
        ent.update(extra)
    return ent


def touch(ent):
    """Refresh updated_at + bump version on mutation."""
    ent["updated_at"] = logical_now_iso()
    ent["version"] = ent.get("version", 1) + 1


def touch_no_version(ent):
    ent["updated_at"] = logical_now_iso()
