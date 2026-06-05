"""Body-shape validation helpers (priority-4 ERR_INVALID_REQUEST, 422).

USPS state codes are validated as two-letter codes. The scaffold says
'two-letter USPS state code'; we accept any two ASCII uppercase letters
(tests drive concrete codes like CA/NY/TX).
"""
import re

from errors import err, ERR_INVALID_REQUEST

NPI_RE = re.compile(r"^\d{10}$")
STATE_RE = re.compile(r"^[A-Za-z]{2}$")


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return val


def require_state(body, field):
    val = require_str(body, field)
    if not STATE_RE.match(val):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a two-letter USPS state code." % field)
    return val


def optional_state(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or not STATE_RE.match(val):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a two-letter USPS state code." % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s." % (field, sorted(allowed)))
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return val


def require_int_min(body, field, minimum):
    val = require_int(body, field)
    if val < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %d." % (field, minimum))
    return val


def require_int_gt(body, field, threshold):
    val = require_int(body, field)
    if val <= threshold:
        raise err(ERR_INVALID_REQUEST, "Field %s must be > %d." % (field, threshold))
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string." % field)
    return val


def require_datetime(body, field):
    """Require an ISO 8601 instant; return the raw string (parse separately)."""
    import db
    val = require(body, field)
    if not isinstance(val, str) or db.parse_iso(val) is None:
        raise err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime." % field)
    return val


def require_str_list(body, field):
    val = require(body, field)
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a list of strings." % field)
    return val
