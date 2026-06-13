"""Input-body parsing helpers. Raise ERR_INVALID_REQUEST on malformed input."""
from flask import request

from errors import err, ERR_INVALID_REQUEST


def body():
    """Parse JSON body, returning {} when absent. Malformed JSON -> 400."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Empty body is fine for many POSTs; only reject when bytes present but unparsable.
        if request.data:
            raise err(ERR_INVALID_REQUEST, "malformed JSON body")
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise err(ERR_INVALID_REQUEST, f"missing required field: {field}")
    return data[field]


def require_str(data, field):
    val = require(data, field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return val


def require_int(data, field, minimum=None, maximum=None):
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} above maximum {maximum}")
    return val


def optional_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} above maximum {maximum}")
    return val


def optional_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return val


def optional_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return val


def require_str_array(data, field):
    val = require(data, field)
    return _check_str_array(val, field)


def optional_str_array(data, field, default=None):
    if field not in data or data[field] is None:
        return [] if default is None else default
    return _check_str_array(data[field], field)


def _check_str_array(val, field):
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an array of strings")
    return val


def require_enum(data, field, allowed):
    val = require(data, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return val
