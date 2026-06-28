"""Request-body validation and parsing helpers.

Well-formedness failures (missing required field, bad enum, out-of-range
integer, etc.) raise ERR_INVALID_REQUEST (422). Pagination/query failures
raise ERR_VALIDATION_PARAM (400).
"""
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST, ERR_VALIDATION_PARAM


def body_obj():
    """Return the request JSON body as a dict (or {} when absent)."""
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def opt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_string(value, field, allow_empty=False):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string." % field)
    if not allow_empty and value.strip() == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must not be blank." % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return value


def as_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s." % (field, maximum))
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise err(ERR_INVALID_REQUEST,
                  "Field %s must be one of %s." % (field, sorted(allowed)))
    return value


def parse_dt(value, field):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime."""
    if not isinstance(value, str) or value.strip() == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime." % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----- pagination / query params (ERR_VALIDATION_PARAM on failure) -----

def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PARAM, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION_PARAM, "limit must be between 1 and 100.")

    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PARAM, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION_PARAM, "offset must be >= 0.")

    return limit, offset


def filter_enum(param_name, value, allowed):
    """Validate an optional filter query value against an enum set."""
    if value is not None and value not in allowed:
        raise err(ERR_VALIDATION_PARAM,
                  "Unknown value for filter %s: %s" % (param_name, value))
    return value
