"""Parsing, shape validation, date helpers, and pagination.

Every shape failure maps to ERR_INVALID_REQUEST (HTTP 400) — the only
request-shape error id this scaffold declares (validations priority 10).
"""
from datetime import datetime, timezone

from flask import request

from errors import ApiError
from response import ok_list


def parse_date(value):
    """Parse a strict YYYY-MM-DD date string into a date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif "T" not in text and len(text) == 10:
        text = text + "T00:00:00+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_date_str(value):
    return isinstance(value, str) and _try(lambda: parse_date(value))


def is_dt_str(value):
    return isinstance(value, str) and _try(lambda: parse_dt(value))


def _try(fn):
    try:
        fn()
        return True
    except Exception:
        return False


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_body():
    """Parse the JSON request body lazily. A body that cannot be parsed at all
    fails at cascade step 10 with ERR_INVALID_REQUEST."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Request body must be a valid JSON object"
            )
        return data
    return {}


def req(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def as_int(v, field):
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_pos_int(v, field):
    if not is_int(v) or v <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be a positive integer"
        )
    return v


def as_nonneg_int(v, field):
    if not is_int(v) or v < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be a non-negative integer"
        )
    return v


def as_int_range(v, field, lo, hi):
    if not is_int(v) or v < lo or v > hi:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {field} must be an integer in [{lo}, {hi}]",
        )
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_enum(v, field, choices):
    if v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be one of {sorted(choices)}"
        )
    return v


def as_date_str(v, field):
    if not is_date_str(v):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be a YYYY-MM-DD date"
        )
    return v.strip()


def as_dt_str(v, field):
    if not is_dt_str(v):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp"
        )
    return v.strip()


def as_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an array")
    return v


def pagination():
    """limit/offset query parameters (defaults 10/0, limit within 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def apply_filters(records, mapping):
    """Exact-match query filters; mapping pairs query param -> record field."""
    out = []
    for r in records:
        keep = True
        for param, field in mapping.items():
            v = request.args.get(param)
            if v is not None and str(r.get(field)) != v:
                keep = False
                break
        if keep:
            out.append(r)
    return out


def respond_list(records, serializer):
    """Sorted by creation order ascending, then paginated."""
    from services import by_seq

    items = by_seq(records)
    limit, offset = pagination()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)
