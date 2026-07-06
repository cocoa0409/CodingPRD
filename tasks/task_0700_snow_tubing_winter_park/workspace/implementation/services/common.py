"""Common system-field bookkeeping and validation helpers."""
from datetime import datetime, timezone

from errors import err

# Entity types that are append-only logs: they carry ONLY id + created_at
# (no updated_at, no version). PRD §2.4.
LOG_TYPES = {"WeatherLog", "RefundEntry"}


def now_iso_ms(store):
    """Audit timestamp. Uses wall-clock for created_at/updated_at (record audit time),
    formatted ISO8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_record(store, entity_type, fields):
    """Create a record dict with system fields populated.

    Full records carry id, created_at, updated_at, version.
    Log records (WeatherLog, RefundEntry) carry only id and created_at.
    """
    ts = now_iso_ms(store)
    rec = dict(fields)
    rec["id"] = store.new_id()
    rec["created_at"] = ts
    rec["_seq"] = store.next_seq()
    rec["_type"] = entity_type
    if entity_type not in LOG_TYPES:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(store, rec):
    """Mark a mutable record as mutated: refresh updated_at, bump version."""
    if rec.get("_type") in LOG_TYPES:
        return
    rec["updated_at"] = now_iso_ms(store)
    rec["version"] = rec.get("version", 1) + 1


# ----- request body validation primitives -----

def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def as_int(body, field, required=True, default=None, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    return value


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    value = body[field]
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    return value


def as_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    value = body[field]
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return value


def as_datetime(body, field, required=True, default=None):
    from clock import parse_iso8601
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    value = body[field]
    dt = parse_iso8601(value)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO8601 datetime.")
    return dt


def iso_z(dt):
    """Serialize a datetime as ISO8601 UTC with three fractional digits and Z suffix."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
