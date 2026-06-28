"""Field-shape validation helpers (ERR_INVALID_FIELD, HTTP 422) and
pagination parsing (PRD §2.3)."""
from datetime import datetime, timezone

from flask import request

import errors
from errors import err

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def invalid(msg):
    return err(errors.ERR_INVALID_FIELD, msg)


def get_body():
    """Parse JSON body; tolerate empty body for action endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid("Request body must be a JSON object.")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise invalid("Field '%s' is required and must be a non-empty string." % field)
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid("Field '%s' is required and must be an integer." % field)
    if minimum is not None and val < minimum:
        raise invalid("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise invalid("Field '%s' must be <= %s." % (field, maximum))
    return val


def optional_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise invalid("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def require_number(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid("Field '%s' is required and must be a number." % field)
    if minimum is not None and val < minimum:
        raise invalid("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise invalid("Field '%s' must be <= %s." % (field, maximum))
    return val


def parse_datetime(body, field):
    """Parse an ISO 8601 datetime; normalize to aware UTC."""
    raw = body.get(field)
    if not isinstance(raw, str) or raw == "":
        raise invalid("Field '%s' is required and must be an ISO 8601 datetime string." % field)
    return parse_iso(raw, field)


def parse_iso(raw, field="value"):
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid("Field '%s' must be a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = PAGINATION_LIMIT_DEFAULT
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise invalid("limit must be an integer.")
        if limit_v < PAGINATION_LIMIT_MIN or limit_v > PAGINATION_LIMIT_MAX:
            raise invalid("limit must be between %s and %s." % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX))
    if offset is None:
        offset_v = PAGINATION_OFFSET_DEFAULT
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise invalid("offset must be an integer.")
        if offset_v < PAGINATION_OFFSET_MIN:
            raise invalid("offset must be >= %s." % PAGINATION_OFFSET_MIN)
    return limit_v, offset_v
