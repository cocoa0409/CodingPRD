from datetime import datetime, timezone

from db import new_id, store
from errors import err, ERR_INVALID_REQUEST


def parse_dt(value, field):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_record(versioned=True):
    """Create base record dict. versioned=False for append-only entities."""
    now = datetime.now(timezone.utc)
    rec = {
        "id": new_id(),
        "_created_dt": now,
        "_seq": store.next_seq(),
        "created_at": iso(now),
    }
    if versioned:
        rec["updated_at"] = iso(now)
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version and updated_at on a mutation."""
    now = datetime.now(timezone.utc)
    rec["updated_at"] = iso(now)
    rec["version"] = rec.get("version", 1) + 1


def require(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def require_str(body, field, allow_empty=False):
    v = require(body, field)
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    if not allow_empty and v.strip() == "":
        raise err(ERR_INVALID_REQUEST, f"{field} must be non-empty")
    return v


def require_int(body, field, minimum=None, maximum=None, exclusive_min=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}")
    if exclusive_min is not None and v <= exclusive_min:
        raise err(ERR_INVALID_REQUEST, f"{field} must be > {exclusive_min}")
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be <= {maximum}")
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def optional_bool(body, field, default=False):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v
