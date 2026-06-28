"""Request-body well-formedness helpers (PRD §2.10 / ERR_INVALID_REQUEST 422).

These run after auth, authorization, and existence checks but before state and
business rules.
"""
import re

from errors import err

_ZIP_RE = re.compile(r"^\d{5}$")


def get_json(request):
    """Return the request JSON body as a dict (empty dict if no/empty body)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def require_positive_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if val <= 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be greater than zero" % field)
    return val


def opt_positive_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_positive_int(body, field)


def require_zip(body, field):
    val = require(body, field)
    if not isinstance(val, str) or not _ZIP_RE.match(val):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a 5-digit ZIP" % field)
    return val


def require_prefix(body, field):
    val = require(body, field)
    if not isinstance(val, str) or not re.match(r"^\d{3}$", val):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a 3-digit ZIP prefix" % field)
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def opt_number(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return val


def require_list(body, field, default=None):
    if field not in body or body[field] is None:
        return default if default is not None else []
    val = body[field]
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a list" % field)
    return val
