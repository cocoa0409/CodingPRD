"""Shared helpers: logical clock, timestamps, parsing, validation, pagination."""

import re
import uuid
from datetime import datetime, timezone, timedelta

from db import db
from errors import err_validation

_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    """Logical clock. Before set, reads 2026-05-01T00:00:00Z. Never wall clock."""
    if db.clock_utc is None:
        return _DEFAULT_CLOCK
    return db.clock_utc


def set_clock(dt: datetime) -> None:
    db.clock_utc = dt


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def now_iso() -> str:
    """Real wall-clock now for api_request_timestamp (envelope metadata)."""
    return format_iso(datetime.now(timezone.utc))


def parse_iso(value):
    """Parse an ISO 8601 timestamp. Accepts trailing Z or offset. Returns aware datetime."""
    if not isinstance(value, str):
        raise err_validation("Timestamp must be a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err_validation(f"Invalid ISO8601 timestamp: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------- validation helpers ----------

def require_field(payload: dict, name: str):
    if not isinstance(payload, dict):
        raise err_validation("Request body must be a JSON object")
    if name not in payload or payload[name] is None:
        raise err_validation(f"Missing required field: {name}")
    return payload[name]


def optional_field(payload: dict, name: str, default=None):
    if not isinstance(payload, dict):
        raise err_validation("Request body must be a JSON object")
    v = payload.get(name, default)
    if v is None:
        return default
    return v


def require_string(payload, name):
    v = require_field(payload, name)
    if not isinstance(v, str) or v == "":
        raise err_validation(f"Field {name} must be a non-empty string")
    return v


def optional_string(payload, name, default=None):
    v = optional_field(payload, name, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_validation(f"Field {name} must be a string")
    return v


def require_int(payload, name, min_value=None, allow_zero=True):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        raise err_validation(f"Field {name} must be >= {min_value}")
    return v


def optional_int(payload, name, default=None, min_value=None):
    if not isinstance(payload, dict):
        raise err_validation("Request body must be a JSON object")
    if name not in payload or payload[name] is None:
        return default
    v = payload[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        raise err_validation(f"Field {name} must be >= {min_value}")
    return v


def require_bool(payload, name):
    v = require_field(payload, name)
    if not isinstance(v, bool):
        raise err_validation(f"Field {name} must be a boolean")
    return v


def optional_bool(payload, name, default=False):
    if not isinstance(payload, dict):
        raise err_validation("Request body must be a JSON object")
    if name not in payload or payload[name] is None:
        return default
    v = payload[name]
    if not isinstance(v, bool):
        raise err_validation(f"Field {name} must be a boolean")
    return v


def require_enum(payload, name, allowed):
    v = require_field(payload, name)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"Field {name} must be one of {sorted(allowed)}")
    return v


def optional_enum(payload, name, allowed, default=None):
    if not isinstance(payload, dict):
        raise err_validation("Request body must be a JSON object")
    if name not in payload or payload[name] is None:
        return default
    v = payload[name]
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_timestamp(payload, name):
    v = require_field(payload, name)
    return parse_iso(v)


def parse_pagination(args):
    """Parse limit/offset query params with defaults 10/0, bounds 1..100 / >=0."""
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def touch(resource: dict) -> None:
    """Bump updated_at and version on a resource that carries common fields."""
    resource["updated_at"] = format_iso(datetime.now(timezone.utc))
    resource["version"] = resource.get("version", 1) + 1


def stamp_new(resource: dict) -> dict:
    """Populate common fields (id, created_at, updated_at, version) on a new resource."""
    ts = format_iso(now_utc())
    resource.setdefault("id", new_id())
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1
    return resource
