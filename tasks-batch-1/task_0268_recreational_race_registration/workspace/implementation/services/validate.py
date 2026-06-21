"""Body-field validation helpers (PRD 2.10 step ERR_INVALID_REQUEST)."""
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from db import db


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a non-empty string" % name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be a string" % name)
    return v


def require_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field '%s' is required and must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (name, minimum))
    return v


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (name, minimum))
    return v


def require_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a number" % name)
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % name)
    return v


def lookup(store, key, label="resource"):
    """Existence check (ERR_NOT_FOUND). store is a dict, key is the id."""
    if key not in store:
        raise err(ERR_NOT_FOUND, "%s not found: %s" % (label, key))
    return store[key]
