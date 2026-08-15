"""Shared helpers: id/timestamp generation, entity construction, validation."""

import re
import uuid
from datetime import date

from db import db
import errors

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """created_at/updated_at use the logical clock, normalized to 3 fractional digits."""
    return normalize_iso(db.current_utc)


def normalize_iso(ts):
    """Normalize an ISO-8601 UTC timestamp to milliseconds precision.

    Accepts forms like 2026-08-01T00:00:00Z or with any fractional digits and
    returns ...T HH:MM:SS.mmmZ. Non-matching strings are returned unchanged.
    """
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$", ts or ""
    )
    if not m:
        return ts
    base, frac = m.group(1), m.group(2) or ""
    frac = (frac + "000")[:3]
    return f"{base}.{frac}Z"


def is_valid_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def parse_date(s):
    return date.fromisoformat(s)


def touch(entity):
    """Bump updated_at and increment version by 1 (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def make_entity(fields):
    """Attach the common identity envelope (§2.4): id, created_at, updated_at, version."""
    ts = now_iso()
    entity = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    entity.update(fields)
    return entity


# ---------- request body validation helpers ----------

def get_json_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def req_string(body, name):
    v = body.get(name)
    if v is None or not isinstance(v, str) or v == "":
        raise errors.validation(f"Field '{name}' is required and must be a non-empty string")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise errors.validation(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_int(body, name, min_value=None, allow_zero=True):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field '{name}' is required and must be an integer")
    if min_value is not None and v < min_value:
        raise errors.validation(f"Field '{name}' must be >= {min_value}")
    if not allow_zero and v == 0:
        raise errors.validation(f"Field '{name}' must be non-zero")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise errors.validation(f"Field '{name}' is required and must be a boolean")
    return v


def req_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.validation(f"Field '{name}' is required and must be a number")
    return v


def req_date(body, name):
    v = body.get(name)
    if not is_valid_date(v):
        raise errors.validation(f"Field '{name}' must be a valid YYYY-MM-DD date")
    return v
