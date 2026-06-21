"""Schema-level request validation (priority 4, ERR_INVALID_REQUEST / 400).

These checks run after auth, authorization and existence (PRD §2.10):
required fields present, enums in allowed set, integers non-negative,
window_end > window_start, lines non-empty.
"""
from errors import err, ERR_INVALID_REQUEST
from clock import parse_iso


def bad(msg):
    raise err(ERR_INVALID_REQUEST, msg)


def get_body():
    from flask import request
    if request.data:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            bad("Request body is not valid JSON.")
    else:
        data = {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            bad("Missing required field: %s" % n)


def require_str(body, name, allow_empty=False):
    v = body.get(name)
    if not isinstance(v, str):
        bad("Field %s must be a string." % name)
    if not allow_empty and v == "":
        bad("Field %s must be non-empty." % name)
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        bad("Field %s must be one of %s." % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    return require_enum(body, name, allowed)


def require_nonneg_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer." % name)
    if v < 0:
        bad("Field %s must be >= 0." % name)
    return v


def opt_nonneg_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    return require_nonneg_int(body, name)


def require_int_min(body, name, minimum):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer." % name)
    if v < minimum:
        bad("Field %s must be >= %d." % (name, minimum))
    return v


def opt_int_min(body, name, minimum, default):
    if name not in body or body[name] is None:
        return default
    return require_int_min(body, name, minimum)


def require_state_code(body, name):
    v = body.get(name)
    if not isinstance(v, str) or len(v) != 2 or not v.isupper():
        bad("Field %s must be a 2-letter uppercase state code." % name)
    return v


def require_dt(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        bad("Field %s must be an ISO 8601 datetime string." % name)
    try:
        return parse_iso(v)
    except Exception:
        bad("Field %s is not a valid ISO 8601 datetime." % name)


def require_window(body):
    ws = require_dt(body, "window_start")
    we = require_dt(body, "window_end")
    if not (we > ws):
        bad("window_end must be strictly after window_start.")
    return ws, we
