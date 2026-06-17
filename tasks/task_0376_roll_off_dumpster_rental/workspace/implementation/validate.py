"""Input validation helpers (PRD section 2.3, 2.9)."""
from flask import request

from errors import err


def get_json_body():
    """Parse the JSON body. A missing/invalid body becomes an empty dict so
    that the required-field checks report ERR_INVALID_REQUEST consistently."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_non_negative_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if val < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= 0" % field)
    return val


def require_int_at_least(body, field, minimum):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %d" % (field, minimum))
    return val


def optional_non_negative_int(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    return require_non_negative_int(body, field)


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def require_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


_DATE_LEN = len("YYYY-MM-DD")


def require_date(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a date string" % field)
    parts = val.split("-")
    if len(val) != _DATE_LEN or len(parts) != 3:
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO YYYY-MM-DD date" % field)
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO YYYY-MM-DD date" % field)
    if not (1 <= m <= 12 and 1 <= d <= 31):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a valid date" % field)
    return val


def get_pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0.
    Malformed values are reported as ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset
