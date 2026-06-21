"""Shared helpers: body parsing, validation, pagination, serialization."""
from datetime import datetime, timezone

from flask import request

import errors


def parse_iso_to_epoch(value):
    """Parse an ISO 8601 datetime string to epoch seconds (float) for ordering.

    Accepts a trailing 'Z' or an explicit offset. Naive datetimes are treated
    as UTC. Raises ERR_INVALID_REQUEST on an unparseable value.
    """
    if not isinstance(value, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def add_days_iso(iso_value, days):
    """Return iso_value (an ISO 8601 UTC stamp) plus `days`, ISO 8601 UTC, 3 fractional digits."""
    from datetime import timedelta

    s = iso_value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

# Pagination defaults (PRD §2.3 / scaffold pagination_defaults).
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def get_body():
    """Return the JSON body as a dict, or {} when absent. Bad JSON -> 422."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # An empty body is acceptable for no-input endpoints; treat as {}.
        if not request.data:
            return {}
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


def require_fields(body, *names):
    for name in names:
        if name not in body or body[name] is None:
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name
            )


def as_int(body, name, *, minimum=None, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name
            )
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        errors.raise_error(
            errors.ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum)
        )
    return val


def as_bool(body, name, *, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name
            )
        return default
    val = body[name]
    if not isinstance(val, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return val


def as_str(body, name, *, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name
            )
        return default
    val = body[name]
    if not isinstance(val, str) or not val.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST, "%s must be a string" % name)
    return val


def as_enum(body, name, allowed, *, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name
            )
        return default
    val = body[name]
    if val not in allowed:
        errors.raise_error(
            errors.ERR_INVALID_REQUEST, "%s must be one of %s" % (name, sorted(allowed))
        )
    return val


def parse_datetime_str(body, name, *, required=True, default=None):
    """Datetimes are carried as ISO 8601 strings; we keep the string verbatim."""
    if name not in body or body[name] is None:
        if required:
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name
            )
        return default
    val = body[name]
    if not isinstance(val, str) or not val.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST, "%s must be a datetime string" % name)
    return val


def paginate(query_args):
    """Read limit/offset query params per PRD §2.3. Returns (limit, offset)."""
    limit = query_args.get("limit")
    offset = query_args.get("offset")
    if limit is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGE_MIN_LIMIT:
            limit = PAGE_MIN_LIMIT
        elif limit > PAGE_MAX_LIMIT:
            limit = PAGE_MAX_LIMIT
    if offset is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def page_slice(rows, limit, offset):
    """Sort by creation order ascending, slice, and build the pagination meta."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, meta


# Internal bookkeeping fields never surfaced in API responses.
_HIDDEN = {"_seq"}


def serialize(obj):
    """Strip internal fields; return a clean public view of a stored row."""
    return {k: v for k, v in obj.items() if k not in _HIDDEN}
