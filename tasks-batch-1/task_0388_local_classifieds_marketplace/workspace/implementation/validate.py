"""Input field validation helpers (priority 20, ERR_INVALID_REQUEST, §1.4)."""
from errors import err


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % name)
    return body[name]


def require_str(body, name, allow_empty=False, max_len=None):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if not allow_empty and val == "":
        raise err("ERR_INVALID_REQUEST", "%s must be non-empty." % name)
    if max_len is not None and len(val) > max_len:
        raise err("ERR_INVALID_REQUEST", "%s exceeds max length." % name)
    return val


def require_int(body, name, minimum=None):
    val = require_field(body, name)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    return val


def optional_int(body, name, minimum=None, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    return val


def optional_str(body, name, default=None, max_len=None, allow_empty=True):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if not allow_empty and val == "":
        raise err("ERR_INVALID_REQUEST", "%s must be non-empty." % name)
    if max_len is not None and len(val) > max_len:
        raise err("ERR_INVALID_REQUEST", "%s exceeds max length." % name)
    return val


def require_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return val


def require_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        if default is not None:
            return default
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s." % name)
    val = body[name]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid value." % name)
    return val
