"""Request-body well-formedness helpers (§1.4 p5, ERR_INVALID_REQUEST)."""
import errors
from timeutil import parse_iso


def _bad(msg):
    raise errors.invalid_request(msg)


def get_body(request):
    if request.data:
        parsed = request.get_json(silent=True)
        if parsed is None:
            _bad("Request body is not valid JSON")
        if not isinstance(parsed, dict):
            _bad("Request body must be a JSON object")
        return parsed
    return {}


def req_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (v == "" and not allow_empty):
        _bad("%s must be a non-empty string" % field)
    return v


def req_int(body, field, min=None, max=None, gt=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        _bad("%s must be an integer" % field)
    if gt is not None and not v > gt:
        _bad("%s must be greater than %s" % (field, gt))
    if min is not None and v < min:
        _bad("%s must be >= %s" % (field, min))
    if max is not None and v > max:
        _bad("%s must be <= %s" % (field, max))
    return v


def req_number(body, field, lo, hi):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("%s must be a number" % field)
    if v < lo or v > hi:
        _bad("%s must be between %s and %s inclusive" % (field, lo, hi))
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        _bad("%s must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad("%s must be one of %s" % (field, sorted(allowed)))
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        _bad("%s must be an ISO 8601 datetime string" % field)
    try:
        parse_iso(v)
    except Exception:
        _bad("%s must be a valid ISO 8601 datetime" % field)
    return v


def opt_enum(body, field, allowed, default):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad("%s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad("%s must be a boolean" % field)
    return v
