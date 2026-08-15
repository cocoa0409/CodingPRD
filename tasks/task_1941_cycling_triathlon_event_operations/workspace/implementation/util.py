"""Shared helpers: UUIDs, timestamps, datetime parsing, common fields."""
import uuid
from datetime import datetime, timezone

import db
from errors import validation


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current wall-clock UTC as ISO 8601 with three fractional digits (for created_at/updated_at)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string into an aware datetime. Accepts trailing Z."""
    if not isinstance(s, str):
        raise validation(f"expected datetime string, got {type(s).__name__}")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise validation(f"invalid datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date_year(s):
    """Extract the year from an ISO date or datetime string."""
    if not isinstance(s, str):
        raise validation("expected date string")
    try:
        return int(s[:4])
    except (ValueError, IndexError):
        raise validation(f"invalid date: {s}")


def clock_dt():
    """Logical clock as an aware datetime."""
    return parse_dt(db.get_clock())


def stamp_common(rec):
    """Add/refresh common fields on a new record."""
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at and version on mutation."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def require_fields(body, fields):
    """Ensure required fields exist in body."""
    if not isinstance(body, dict):
        raise validation("request body must be a JSON object")
    for f in fields:
        if f not in body or body[f] is None:
            raise validation(f"missing required field: {f}")


def require_enum(value, allowed, name):
    if value not in allowed:
        raise validation(f"invalid {name}: {value}")
    return value


def require_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation(f"{name} must be an integer")
    return value


def require_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation(f"{name} must be a number")
    return value


def require_bool(value, name):
    if not isinstance(value, bool):
        raise validation(f"{name} must be a boolean")
    return value
