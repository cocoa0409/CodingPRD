"""Request parsing, validation, pagination, datetime helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err, ERR_INVALID_REQUEST


def get_body():
    """Return the JSON body as a dict (empty dict if none). Malformed JSON or a
    non-object body is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        err(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return val


def _is_bool(v):
    return isinstance(v, bool)


def require_int(body, field, min_value=None, max_value=None):
    val = require(body, field)
    # bool is a subclass of int — reject explicitly.
    if _is_bool(val) or not isinstance(val, int):
        err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if min_value is not None and val < min_value:
        err(ERR_INVALID_REQUEST, "Field %s out of range" % field)
    if max_value is not None and val > max_value:
        err(ERR_INVALID_REQUEST, "Field %s out of range" % field)
    return val


def opt_int(body, field, default=None, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if _is_bool(val) or not isinstance(val, int):
        err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if min_value is not None and val < min_value:
        err(ERR_INVALID_REQUEST, "Field %s out of range" % field)
    if max_value is not None and val > max_value:
        err(ERR_INVALID_REQUEST, "Field %s out of range" % field)
    return val


def require_number(body, field):
    val = require(body, field)
    if _is_bool(val) or not isinstance(val, (int, float)):
        err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return float(val)


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if _is_bool(val) or not isinstance(val, (int, float)):
        err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return float(val)


def require_enum(body, field, choices):
    val = require_str(body, field)
    if val not in choices:
        err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, choices))
    return val


def opt_enum(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in choices:
        err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, choices))
    return val


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime."""
    if not isinstance(value, str) or value == "":
        err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except Exception:
        err(ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_datetime(body, field):
    val = require(body, field)
    return parse_datetime(val, field)


# ---------------------------------------------------------------------------
# Pagination — PRD 2.3
# limit default 10, min 1, max 100; offset default 0, min 0.
# A request asking for more than 100 is treated as out of range.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = _parse_pag_param("limit", default=10, minimum=1, maximum=100)
    offset = _parse_pag_param("offset", default=0, minimum=0, maximum=None)
    return limit, offset


def _parse_pag_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        err(ERR_INVALID_REQUEST, "Query param %s must be an integer" % name)
    if val < minimum:
        err(ERR_INVALID_REQUEST, "Query param %s below minimum" % name)
    if maximum is not None and val > maximum:
        err(ERR_INVALID_REQUEST, "Query param %s above maximum" % name)
    return val


def paginate(records, limit, offset):
    """PRD 2.3: order by created_at ascending, id as deterministic tie-break;
    total_count is the count before the page window; return the window slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
