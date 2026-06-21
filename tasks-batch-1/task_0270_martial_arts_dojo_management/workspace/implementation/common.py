"""Shared helpers: pagination, datetime parsing, body validation, rounding."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err, ERR_INVALID_REQUEST

# Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def round_half_up(value):
    """Round a Decimal/number half-up to the nearest whole integer (cents).

    Half-up = away from zero on .5 (PRD §2.7)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_pagination():
    """Return (limit, offset). Raises ERR_INVALID_REQUEST on malformed/out-of-range
    values (PRD §2.3: limit 1..100 default 10; offset >= 0 default 0)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err(ERR_INVALID_REQUEST, "limit out of range (1..100).")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Return (page_items, pagination_meta). `items` already filtered & sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    """List results are ordered by created_at ascending (PRD §2.3).

    created_at strings are ISO 8601 and lexically ordered; ties broken by id
    for stable ordering across identical timestamps."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def get_json_body():
    """Return the parsed JSON object body, or {} if absent. Raises
    ERR_INVALID_REQUEST if the body is present but not a JSON object."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def parse_iso8601(value, error_spec=ERR_INVALID_REQUEST):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Raises error_spec on malformed input."""
    if not isinstance(value, str) or not value:
        raise err(error_spec, "Expected an ISO 8601 timestamp string.")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(error_spec, "Malformed ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    """ISO 8601 UTC string with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def require_fields(body, fields):
    """Ensure each named field is present (not None) in the body."""
    for f in fields:
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}.")


def require_str(value, field, min_len=1, max_len=None, trim=False):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string.")
    v = value.strip() if trim else value
    if len(v) < min_len:
        raise err(ERR_INVALID_REQUEST, f"{field} must be at least {min_len} chars.")
    if max_len is not None and len(value) > max_len:
        raise err(ERR_INVALID_REQUEST, f"{field} must be at most {max_len} chars.")
    return value


def require_int(value, field, minimum=None, maximum=None, allowed=None,
                error_spec=ERR_INVALID_REQUEST):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(error_spec, f"{field} must be an integer.")
    if minimum is not None and value < minimum:
        raise err(error_spec, f"{field} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise err(error_spec, f"{field} must be <= {maximum}.")
    if allowed is not None and value not in allowed:
        raise err(error_spec, f"{field} must be one of {sorted(allowed)}.")
    return value


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}.")
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean.")
    return value


def require_email(value, field):
    if not isinstance(value, str) or "@" not in value:
        raise err(ERR_INVALID_REQUEST, f"{field} must be a valid email containing '@'.")
    return value
