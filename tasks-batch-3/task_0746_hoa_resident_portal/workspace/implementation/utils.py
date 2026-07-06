"""Time parsing, UUID generation, decimal helpers, and payload validation."""

import re
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_error


# ---------------- UUID / request-id ---------------- #

def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


# ---------------- Timestamps ---------------- #

def now_iso(current_utc_iso):
    """Return the current logical clock as-is — the caller has already formatted it."""
    return current_utc_iso


def dt_to_iso(dt):
    """Serialize datetime to ISO 8601 UTC with milliseconds and 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC string; returns aware datetime in UTC.
    Accepts fractional seconds and either 'Z' or +HH:MM offsets.
    Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(s, str):
        raise_error("ERR_INVALID_REQUEST", "invalid timestamp type")
    try:
        # Accept variants like 2026-03-01T00:00:00Z / 2026-03-01T00:00:00.000Z / +00:00
        v = s
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise_error("ERR_INVALID_REQUEST", f"invalid ISO 8601 timestamp: {s}")


def parse_iso_or_none(s):
    if s is None:
        return None
    return parse_iso(s)


def iso_now_from_clock(current_utc_iso):
    """Parse the current clock string, returning aware datetime."""
    return parse_iso(current_utc_iso)


# ---------------- Decimal / rounding ---------------- #

def round_half_up(value):
    """Round a numeric value to the nearest integer using half-up. Returns Python int."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------- Payload validation ---------------- #

def require_json(request):
    """Return the request JSON body or raise ERR_INVALID_REQUEST."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            body = request.get_json(silent=True)
        except Exception:
            body = None
        if body is None:
            # DELETE with no body is legal
            if request.method == "DELETE":
                return {}
            # POST endpoints that take no input (e.g. /assessments/{id}/place-lien)
            # are still allowed to omit a body — treat as {}.
            return {}
        if not isinstance(body, dict):
            raise_error("ERR_INVALID_REQUEST", "JSON body must be an object")
        return body
    return {}


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error("ERR_INVALID_REQUEST", f"missing required field: {f}")


def require_str(body, key, allow_empty=False):
    v = body.get(key)
    if not isinstance(v, str):
        raise_error("ERR_INVALID_REQUEST", f"{key} must be a string")
    if not allow_empty and v == "":
        raise_error("ERR_INVALID_REQUEST", f"{key} must be non-empty")
    return v


def require_int(body, key, minimum=None, maximum=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"{key} must be an integer")
    if minimum is not None and v < minimum:
        raise_error("ERR_INVALID_REQUEST", f"{key} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise_error("ERR_INVALID_REQUEST", f"{key} must be <= {maximum}")
    return v


def require_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        raise_error("ERR_INVALID_REQUEST", f"{key} must be a boolean")
    return v


def require_enum(body, key, choices):
    v = body.get(key)
    if v not in choices:
        raise_error("ERR_INVALID_REQUEST", f"{key} must be one of {sorted(choices)}")
    return v


def optional_int(body, key, minimum=None, maximum=None, default=None):
    if key not in body or body[key] is None:
        return default
    return require_int(body, key, minimum=minimum, maximum=maximum)


def optional_str(body, key, default=None, allow_empty=True):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise_error("ERR_INVALID_REQUEST", f"{key} must be a string")
    if not allow_empty and v == "":
        raise_error("ERR_INVALID_REQUEST", f"{key} must be non-empty")
    return v


def optional_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    return require_bool(body, key)


# ---------------- Pagination ---------------- #

def paginate(items, request):
    """Slice `items` list according to `limit` / `offset` query params.
    Returns (page, meta_dict)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_error("ERR_INVALID_REQUEST", "invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        raise_error("ERR_INVALID_REQUEST", "pagination parameters out of range")
    total = len(items)
    page = items[offset: offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
