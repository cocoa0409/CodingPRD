"""Shared helpers: timestamps (logical clock), ids, datetime parsing, and
common-field entity creation/mutation.

Timestamp format (PRD §2.2/§2.5): ISO 8601 UTC with three fractional digits,
e.g. 2026-08-01T00:00:00.000Z.
"""

import secrets
import uuid
from datetime import datetime, timezone

from db import db
from errors import validation


def now_dt():
    """Current logical time as a tz-aware UTC datetime."""
    return db.clock


def fmt_ts(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(db.clock)


def new_req_id():
    return "req_" + secrets.token_hex(10)


def new_id():
    return str(uuid.uuid4())


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime (or date) into a tz-aware UTC datetime.

    Accepts a trailing 'Z' and date-only forms; naive values are read as UTC.
    """
    if not isinstance(value, str) or not value.strip():
        raise validation(f"Field '{field}' must be an ISO 8601 datetime string.")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise validation(f"Field '{field}' is not a valid ISO 8601 datetime: {value!r}.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_common(entity):
    """Attach the standard system-managed fields (PRD §2.5) to a new entity."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def stamp_survey(entity):
    """PopulationSurvey carries only id and created_at (PRD §2.5 exception)."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and increment version on a mutation (PRD §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def sorted_created(items):
    """Default list order: created_at ascending (PRD §2.3). Insertion sequence
    breaks ties deterministically when several rows share a logical instant."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def public(entity):
    """Strip internal bookkeeping keys (prefixed with '_') for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# --- typed request-field readers -------------------------------------------

_MISSING = object()


def req_field(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        raise validation(f"Missing required field: '{name}'.")
    return value


def req_str(body, name):
    value = req_field(body, name)
    if not isinstance(value, str):
        raise validation(f"Field '{name}' must be a string.")
    return value


def req_bool(body, name):
    value = req_field(body, name)
    if not isinstance(value, bool):
        raise validation(f"Field '{name}' must be a boolean.")
    return value


def opt_bool(body, name, default):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        raise validation(f"Field '{name}' must be a boolean.")
    return value


def opt_str(body, name, default=""):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        raise validation(f"Field '{name}' must be a string.")
    return value


def req_int(body, name, minimum=None):
    value = req_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation(f"Field '{name}' must be an integer.")
    if minimum is not None and value < minimum:
        raise validation(f"Field '{name}' must be >= {minimum}.")
    return value


def opt_int_default(body, name, default, minimum=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation(f"Field '{name}' must be an integer.")
    if minimum is not None and value < minimum:
        raise validation(f"Field '{name}' must be >= {minimum}.")
    return value


def req_enum(body, name, allowed):
    value = req_field(body, name)
    if value not in allowed:
        raise validation(
            f"Field '{name}' must be one of {sorted(allowed)}; got {value!r}.")
    return value
