"""Generic request-validation helpers (PRD §2.11, §2.3)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import err

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
CLASS_CODE_RE = re.compile(r"^[A-Z0-9_]{1,32}$")
UPPER_CODE_RE = re.compile(r"^[A-Z]{1,32}$")


def get_json():
    """Return the request JSON body as a dict (empty dict when absent)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    if not allow_empty and v.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be non-empty." % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    # bool is a subclass of int — reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    return v


def require_number(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def parse_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime string." % field)
    dt = _parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime." % field)
    return dt


def _parse_iso(v):
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """Parse limit/offset query params with bounds (PRD §2.3)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0.")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
