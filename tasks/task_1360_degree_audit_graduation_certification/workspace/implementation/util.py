"""Shared utilities: ids, timestamps, field validation helpers, body parsing."""

import re
import uuid
from datetime import datetime, timezone

from flask import request

from errors import ApiError

# ---------------------------------------------------------------------------
# Id / timestamp generation
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------


def json_body():
    if not request.is_json:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be JSON.")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


_MISSING = object()


def require(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING or v is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return v


def optional(body, field, default=None):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        return default
    return v


def as_str(v, field):
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def as_number(v, field):
    """Accept int/float; reject bool/str/None. Returns int if integral."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"Field {field} must be one of: {', '.join(allowed)}.",
        )
    return v


def as_str_list(v, field):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an array of strings.")
    return v


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def as_iso_date(v, field):
    if not isinstance(v, str) or not _ISO_DATE_RE.match(v):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO date (YYYY-MM-DD).")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO date (YYYY-MM-DD).")
    return v


def as_iso_datetime(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO8601 datetime.")
    try:
        parse_iso8601(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO8601 datetime.")
    return v


def parse_iso8601(s):
    """Parse an ISO8601 string to an aware datetime (UTC assumed if no offset)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Pagination slice helper
# ---------------------------------------------------------------------------


def paginate(items, limit, offset):
    """Sort by created_at asc (then id for stable order) and slice."""
    sorted_items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(sorted_items)
    page = sorted_items[offset : offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Generic resource factory (common_fields)
# ---------------------------------------------------------------------------


def make_resource(fields):
    """Create a resource dict with the standard system fields."""
    ts = now_iso()
    r = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    r.update(fields)
    return r


def touch(resource):
    """Bump updated_at and version for a mutation."""
    resource["updated_at"] = now_iso()
    resource["version"] += 1
