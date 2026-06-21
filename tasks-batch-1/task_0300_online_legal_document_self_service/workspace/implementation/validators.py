"""Request-field validation helpers (ERR_INVALID_REQUEST / 400)."""

import errors


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return body[name]


def require_string(body, name, allow_empty=False):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {name} must be a string")
    if not allow_empty and val.strip() == "":
        raise errors.invalid_request(f"Field {name} must be non-empty")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            f"Field {name} must be one of {sorted(allowed)}"
        )
    return val


def require_int(body, name, minimum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}")
    return val


def require_number(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field {name} must be <= {maximum}")
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return val


def optional_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return val


def require_string_array(body, name, non_empty=True):
    val = require_field(body, name)
    if not isinstance(val, list):
        raise errors.invalid_request(f"Field {name} must be an array")
    if non_empty and len(val) == 0:
        raise errors.invalid_request(f"Field {name} must be non-empty")
    for item in val:
        if not isinstance(item, str) or item.strip() == "":
            raise errors.invalid_request(f"Field {name} must contain non-empty strings")
    return val


def require_object(body, name):
    val = require_field(body, name)
    if not isinstance(val, dict):
        raise errors.invalid_request(f"Field {name} must be an object")
    return val
