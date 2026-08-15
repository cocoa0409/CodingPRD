"""Request-body schema helpers (validation priority 4 -> ERR_VALIDATION)."""
from flask import request

from db import parse_dt
from errors import err_validation


def json_body():
    """Parse the JSON body; an absent/unparseable/non-object body reads as {}."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise err_validation("Field '%s' is required and must be a non-empty string." % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_validation("Field '%s' must be a string." % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("Field '%s' must be one of %s." % (field, sorted(allowed)))
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        raise err_validation("Field '%s' is required and must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err_validation("Field '%s' must be >= %s." % (field, minimum))
    return v


def opt_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise err_validation("Field '%s' must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err_validation("Field '%s' must be >= %s." % (field, minimum))
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_validation("Field '%s' is required and must be a boolean." % field)
    return v


def opt_bool(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err_validation("Field '%s' must be a boolean." % field)
    return v


def req_number(body, field):
    v = body.get(field)
    if not _is_int(v) and not isinstance(v, float):
        raise err_validation("Field '%s' is required and must be a number." % field)
    return v


def opt_number(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not _is_int(v) and not isinstance(v, float):
        raise err_validation("Field '%s' must be a number." % field)
    return v


def req_datetime_str(body, field):
    """Required ISO 8601 datetime; returns the verbatim string (echoed back)."""
    v = body.get(field)
    if not isinstance(v, str) or parse_dt(v) is None:
        raise err_validation("Field '%s' is required and must be an ISO 8601 datetime." % field)
    return v


def req_version(body, field):
    """OCC expected_*_version: required, integer (numeric strings coerced)."""
    v = body.get(field)
    if v is None:
        raise err_validation("Field '%s' is required." % field)
    if _is_int(v):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            pass
    raise err_validation("Field '%s' must be an integer." % field)
