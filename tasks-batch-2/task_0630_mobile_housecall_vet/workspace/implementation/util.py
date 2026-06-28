"""Shared parsing / validation helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err


def get_json_body():
    """Parse request JSON; tolerate empty body for no-input transition endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        # Non-empty but unparseable, or non-object JSON.
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def pagination_params():
    """Read limit/offset query params (PRD §2.3). Returns (limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Slice a list after sorting by created_at ASC (caller pre-sorts)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
