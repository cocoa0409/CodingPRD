"""Input parsing / well-typedness helpers (ERR_INVALID_REQUEST, 400).

These run AFTER existence checks (PRD 2.5 / 2.8): existence of every referenced
resource precedes field validation. Callers therefore resolve path/FK existence
(ERR_NOT_FOUND) before invoking these helpers.
"""
from datetime import datetime, timezone

from flask import request

import errors
from errors import ApiError


def get_json():
    """Parse the JSON body, tolerating an empty body as an empty object."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def _bad(msg):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, msg)


def require_str(body, field, allow_empty=False):
    if field not in body or body[field] is None:
        _bad("Missing required field: " + field)
    val = body[field]
    if not isinstance(val, str):
        _bad("Field must be a string: " + field)
    if not allow_empty and val.strip() == "":
        _bad("Field must be non-empty: " + field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        _bad("Field must be a string: " + field)
    return val


def require_int(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: " + field)
    val = body[field]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        _bad("Field must be an integer: " + field)
    return val


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        _bad("Field must be an integer: " + field)
    return val


def require_number(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: " + field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _bad("Field must be a number: " + field)
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        _bad("Field must be a boolean: " + field)
    return val


def require_enum(body, field, members):
    val = require_str(body, field)
    if val not in members:
        _bad("Field " + field + " must be one of " + ", ".join(members))
    return val


def opt_enum(body, field, members, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in members:
        _bad("Field " + field + " must be one of " + ", ".join(members))
    return val


def require_datetime(body, field):
    """Parse an ISO 8601 datetime field into a tz-aware UTC datetime."""
    raw = require_str(body, field)
    return parse_iso(raw, field)


def parse_iso(raw, field="datetime"):
    if not isinstance(raw, str):
        _bad("Field must be an ISO 8601 string: " + field)
    txt = raw.strip()
    # Accept trailing 'Z' as UTC.
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        _bad("Field is not a valid ISO 8601 datetime: " + field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_pagination():
    """Read limit/offset query params per PRD 2.3 (default 10, min 1, max 100; offset default 0)."""
    args = request.args

    def parse_int_param(name, default):
        raw = args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            _bad("Query parameter " + name + " must be an integer.")

    limit = parse_int_param("limit", 10)
    offset = parse_int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def to_iso(dt):
    """Render a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
