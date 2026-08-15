"""Request-body schema validation (SCAFFOLD validations priority 4 /
PRD section 2.8 tier 4). All failures are ERR_INVALID_REQUEST (400)."""
from flask import request

from errors import invalid_request
from util import parse_date


def body():
    """Parsed JSON object body; a missing/non-object body is treated as {}."""
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        return {}
    return b


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str):
        raise invalid_request("Field '{}' is required and must be a string".format(field))
    return v


def req_int(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("Field '{}' is required and must be an integer".format(field))
    return v


def req_bool(b, field):
    v = b.get(field)
    if not isinstance(v, bool):
        raise invalid_request("Field '{}' is required and must be a boolean".format(field))
    return v


def req_enum(b, field, allowed):
    v = b.get(field)
    if v not in allowed:
        raise invalid_request(
            "Field '{}' must be one of {}".format(field, ", ".join(allowed))
        )
    return v


def req_date(b, field):
    """Required strict YYYY-MM-DD date; returned normalized as the input string."""
    v = b.get(field)
    if parse_date(v) is None:
        raise invalid_request(
            "Field '{}' is required and must be a YYYY-MM-DD date".format(field)
        )
    return v
