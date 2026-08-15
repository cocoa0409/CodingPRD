"""Shared helpers: logical clock, datetime/date parsing, validation, pagination."""
import re
from datetime import datetime, timezone

from flask import request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST

MISSING = object()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_now():
    return store.clock


def now_iso():
    return fmt_dt(store.clock)


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_valid_date_str(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def new_entity(fields):
    """Create a versioned entity record (common_fields: true)."""
    ent = dict(fields)
    ent["_seq"] = store.next_seq()
    ent["created_at"] = now_iso()
    ent["updated_at"] = ent["created_at"]
    ent["version"] = 1
    return ent


def new_event(fields):
    """Create an append-only event record (id + created_at only)."""
    ent = dict(fields)
    ent["_seq"] = store.next_seq()
    ent["created_at"] = now_iso()
    return ent


def touch(ent):
    """Refresh updated_at and bump version on a mutated versioned entity."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def pub(ent):
    """Public serialization: strip private keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Request body + field validation (ERR_INVALID_REQUEST on shape violations)
# ---------------------------------------------------------------------------
def get_json_body(required):
    body = request.get_json(silent=True, force=True)
    if body is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def req_str(body, name):
    v = body.get(name, MISSING)
    if v is MISSING:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string.")
    return v


def req_int(body, name, min_v=None, max_v=None):
    v = body.get(name, MISSING)
    if v is MISSING:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return _check_int(v, name, min_v, max_v)


def opt_int(body, name, default=None, min_v=None, max_v=None, allow_null=False):
    v = body.get(name, MISSING)
    if v is MISSING:
        return default
    if v is None and allow_null:
        return None
    return _check_int(v, name, min_v, max_v)


def _check_int(v, name, min_v, max_v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer.")
    if min_v is not None and v < min_v:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be >= {min_v}.")
    if max_v is not None and v > max_v:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be <= {max_v}.")
    return v


def req_enum(body, name, allowed):
    v = body.get(name, MISSING)
    if v is MISSING:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"Field {name} must be one of {sorted(allowed)}.")
    return v


def opt_enum(body, name, allowed, default=MISSING):
    v = body.get(name, MISSING)
    if v is MISSING:
        if default is MISSING:
            return MISSING
        return default
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"Field {name} must be one of {sorted(allowed)}.")
    return v


def opt_str(body, name, default=MISSING):
    v = body.get(name, MISSING)
    if v is MISSING:
        return default
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string.")
    return v


def req_datetime(body, name):
    v = body.get(name, MISSING)
    if v is MISSING:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    dt = parse_dt(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an ISO-8601 datetime.")
    return dt


def req_date(body, name):
    v = body.get(name, MISSING)
    if v is MISSING:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    if not is_valid_date_str(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a YYYY-MM-DD date.")
    return v


# ---------------------------------------------------------------------------
# Pagination (limit/offset per SCAFFOLD response_envelope)
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter limit must be between 1 and 100.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter offset must be >= 0.")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def sorted_by_created(items):
    """Default sort: created_at ascending (stable via insertion sequence)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
