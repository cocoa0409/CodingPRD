"""Body validation helpers (ERR_VALIDATION, priority 17)."""
from errors import err, ERR_VALIDATION


def get_body():
    from flask import request
    if request.data:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
    else:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_VALIDATION, "Field '%s' must be a non-empty string" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err(ERR_VALIDATION, "Field '%s' must be a non-empty string" % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, "Field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err(ERR_VALIDATION, "Field '%s' must be >= %s" % (field, minimum))
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum)


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_VALIDATION, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_VALIDATION, "Field '%s' must be a boolean" % field)
    return v


def opt_number(body, field, default=None):
    """Optional numeric value (e.g. shoe_size). null/absent -> default."""
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_VALIDATION, "Field '%s' must be a number" % field)
    return v


def require_iso(body, field):
    from util import parse_iso
    v = body.get(field)
    if not isinstance(v, str):
        raise err(ERR_VALIDATION, "Field '%s' must be an ISO 8601 string" % field)
    try:
        return parse_iso(v)
    except Exception:
        raise err(ERR_VALIDATION, "Field '%s' is not a valid ISO 8601 instant" % field)


def opt_str_array(body, field, default=None):
    if field not in body or body[field] is None:
        return default if default is not None else []
    v = body[field]
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise err(ERR_VALIDATION, "Field '%s' must be an array of strings" % field)
    return list(v)
