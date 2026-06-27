"""Shared validation / parsing / pagination utilities."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

# Pagination defaults (PRD §2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_json_body():
    """Parse JSON body; missing/empty body -> {}. Malformed -> ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def invalid(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", msg)


def require_field(body, name):
    if name not in body or body[name] is None:
        raise invalid("Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise invalid("Field %s must be a non-empty string" % name)
    return val


def optional_string(body, name):
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if not isinstance(val, str):
        raise invalid("Field %s must be a string" % name)
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        raise invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def optional_enum(body, name, allowed):
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        raise invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def _is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)


def require_int(body, name, minimum=None, positive=False):
    val = require_field(body, name)
    if not _is_int(val):
        raise invalid("Field %s must be an integer" % name)
    if positive and val <= 0:
        raise invalid("Field %s must be positive" % name)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (name, minimum))
    return val


def optional_int(body, name, default=None, minimum=None, positive=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not _is_int(val):
        raise invalid("Field %s must be an integer" % name)
    if positive and val <= 0:
        raise invalid("Field %s must be positive" % name)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (name, minimum))
    return val


def require_number(body, name, minimum=None, maximum=None,
                   minimum_exclusive=None, maximum_exclusive=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid("Field %s must be a number" % name)
    if minimum is not None and val < minimum:
        raise invalid("Field %s must be >= %s" % (name, minimum))
    if minimum_exclusive is not None and val <= minimum_exclusive:
        raise invalid("Field %s must be > %s" % (name, minimum_exclusive))
    if maximum is not None and val > maximum:
        raise invalid("Field %s must be <= %s" % (name, maximum))
    if maximum_exclusive is not None and val >= maximum_exclusive:
        raise invalid("Field %s must be < %s" % (name, maximum_exclusive))
    return val


def require_bool(body, name, default=None):
    if name not in body or body[name] is None:
        if default is not None:
            return default
        raise invalid("Missing required field: %s" % name)
    val = body[name]
    if not isinstance(val, bool):
        raise invalid("Field %s must be a boolean" % name)
    return val


def parse_datetime(value, field_name="datetime"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise invalid("Field %s must be an ISO 8601 datetime string" % field_name)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("Field %s is not a valid ISO 8601 datetime" % field_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_datetime(body, name):
    val = require_field(body, name)
    return parse_datetime(val, name)


def get_pagination():
    """Parse limit/offset query params (PRD §2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise invalid("limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset must be >= 0")

    return limit, offset


def paginate(records):
    """Sort by created_at ASC (insertion seq tiebreak) and page."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def round_half_up(value):
    """Round a Decimal/number to whole units using ROUND_HALF_UP -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
