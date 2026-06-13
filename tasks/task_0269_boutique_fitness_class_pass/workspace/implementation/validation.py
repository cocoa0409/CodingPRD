"""Request body / query validation helpers (§2.3, §2.9, ERR_INVALID_REQUEST)."""

from datetime import datetime, timezone

from flask import request

from errors import err


def get_json_body():
    """Parse the JSON body; an absent body is treated as {}.

    A malformed (non-JSON) body is a 422 ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return value


def as_int(value, field, minimum=None, maximum=None):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be <= {maximum}")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return value


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; return a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime string")
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """limit (default 10, [1,100]) and offset (default 0) per §2.3."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order (created_at ASC via _seq), slice, return page+meta."""
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
