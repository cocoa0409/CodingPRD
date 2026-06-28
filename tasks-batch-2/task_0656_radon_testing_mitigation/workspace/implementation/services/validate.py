"""Request-body well-formedness helpers (ERR_INVALID_REQUEST, priority 20 / PRD §2.5).

These raise the lowest-priority body-shape error only after the structural gates
(auth, RBAC, existence, state, OCC, business rules) have passed in the route.
"""

import errors
from errors import ApiError
from db import parse_iso8601


def bad_request(message):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def require_field(body, name):
    if name not in body or body[name] is None:
        bad_request("Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    value = require_field(body, name)
    if not isinstance(value, str) or value.strip() == "":
        bad_request("Field %s must be a non-empty string." % name)
    return value


def require_enum(body, name, allowed):
    value = require_field(body, name)
    if value not in allowed:
        bad_request("Field %s must be one of %s." % (name, sorted(allowed)))
    return value


def optional_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if value not in allowed:
        bad_request("Field %s must be one of %s." % (name, sorted(allowed)))
    return value


def require_int(body, name, minimum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field %s must be >= %s." % (name, minimum))
    return value


def optional_int(body, name, default, minimum=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field %s must be >= %s." % (name, minimum))
    return value


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad_request("Field %s must be a boolean." % name)
    return value


def require_number(body, name, minimum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("Field %s must be a number." % name)
    if minimum is not None and value < minimum:
        bad_request("Field %s must be >= %s." % (name, minimum))
    return value


def optional_number(body, name, default, minimum=None, strictly_positive=False):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("Field %s must be a number." % name)
    if minimum is not None and value < minimum:
        bad_request("Field %s must be >= %s." % (name, minimum))
    if strictly_positive and value <= 0:
        bad_request("Field %s must be > 0." % name)
    return value


def require_datetime(body, name):
    value = require_field(body, name)
    try:
        return parse_iso8601(value)
    except (ValueError, TypeError):
        bad_request("Field %s must be an ISO 8601 UTC datetime." % name)


def optional_datetime(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    try:
        return parse_iso8601(body[name])
    except (ValueError, TypeError):
        bad_request("Field %s must be an ISO 8601 UTC datetime." % name)
