"""Request parsing, field validation, pagination, and serialization helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err

# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------


def body():
    """Parse the JSON request body, tolerating an empty/absent body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        # Body present but not a JSON object.
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(data, *names):
    """ERR_INVALID_REQUEST when any required field is missing (priority 22)."""
    for name in names:
        if name not in data or data[name] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")


def as_str(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
        return None
    value = data[name]
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string.")
    return value


def as_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean.")
    return value


def as_int(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
        return default
    value = data[name]
    # bool is a subclass of int; reject it as an integer field.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer.")
    return value


def as_number(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number.")
    return value


def as_enum(data, name, choices, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
        return default
    value = data[name]
    if value not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field {name} has an invalid value.")
    return value


# ---------------------------------------------------------------------------
# Datetime / date parsing
# ---------------------------------------------------------------------------


def parse_datetime(data, name, required=True):
    """Parse an ISO 8601 UTC datetime. Returns a tz-aware datetime in UTC."""
    raw = as_str(data, name, required=required)
    if raw is None:
        return None
    return _parse_dt_value(raw, name)


def _parse_dt_value(raw, name):
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {name} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_str(data, name, required=True):
    """Validate a YYYY-MM-DD calendar date string; return it unchanged."""
    raw = as_str(data, name, required=required)
    if raw is None:
        return None
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a YYYY-MM-DD date.")
    return raw


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------


def pagination():
    limit = _int_query("limit", 10)
    offset = _int_query("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _int_query(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Serialization: strip internal-only fields (those prefixed with `_`).
# ---------------------------------------------------------------------------


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
