"""Field-shape validation helpers (priority 14, ERR_INVALID_REQUEST)."""
from flask import request

import errors


def body():
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST if malformed."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # empty body is acceptable for no-input endpoints
        if request.data.strip() == b"":
            return {}
        raise errors.invalid_request("Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require(data, key):
    if key not in data or data[key] is None:
        raise errors.invalid_request("Missing required field: %s" % key)
    return data[key]


def require_str(data, key):
    val = require(data, key)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field %s must be a non-empty string." % key)
    return val


def require_int(data, key):
    val = require(data, key)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % key)
    return val


def opt_int(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % key)
    return val


def require_enum(data, key, allowed):
    val = require(data, key)
    if val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s." % (key, sorted(allowed)))
    return val


def opt_bool(data, key, default=False):
    if key not in data or data[key] is None:
        return default
    val = data[key]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a boolean." % key)
    return val


def require_number(data, key):
    val = require(data, key)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % key)
    return val
