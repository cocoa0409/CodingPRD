"""Shared request-parsing helpers: pagination, datetime parsing, field validation."""
from datetime import datetime, timezone

from flask import request

import errors


def parse_pagination():
    """PRD §2.3: limit default 10, min 1, max 100; offset default 0, non-negative.
    Out of range -> ERR_VALIDATION (422)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset may not be negative")

    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page slice."""
    return items[offset:offset + limit]


def get_json_body():
    """Return the parsed JSON body as a dict (or {} when empty)."""
    if request.data is None or len(request.data) == 0:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        # body present but not valid JSON
        raise errors.invalid_request("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def parse_iso8601(s):
    """Parse an ISO 8601 instant into an aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def require_non_negative_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool):
        raise errors.invalid_request("%s must be an integer" % field)
    if value < 0:
        raise errors.invalid_request("%s must be non-negative" % field)
    return value


def require_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool):
        raise errors.invalid_request("%s must be an integer" % field)
    return value


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("%s must be a non-empty string" % field)
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise errors.invalid_request("%s must be a boolean" % field)
    return value


def require_enum(value, field, allowed):
    if value not in allowed:
        raise errors.invalid_request("%s must be one of %s" % (field, sorted(allowed)))
    return value
