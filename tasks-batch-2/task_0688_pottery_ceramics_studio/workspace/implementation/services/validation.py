"""Field-shape validation helpers (SCAFFOLD validation priority 19, PRD §2.10).

Field-shape failures surface as ERR_INVALID_REQUEST (400): required fields
present, enums within allowed values, integers non-negative where required.
"""

from errors import invalid_request


def require_body(payload):
    if payload is None or not isinstance(payload, dict):
        raise invalid_request("request body must be a JSON object")
    return payload


def require_field(payload, field):
    if field not in payload or payload[field] is None:
        raise invalid_request("missing required field: %s" % field)
    return payload[field]


def require_str(payload, field):
    val = require_field(payload, field)
    if not isinstance(val, str) or val == "":
        raise invalid_request("field %s must be a non-empty string" % field)
    return val


def require_int(payload, field, minimum=None):
    val = require_field(payload, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid_request("field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise invalid_request("field %s must be >= %s" % (field, minimum))
    return val


def optional_int(payload, field, default=None, minimum=None):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid_request("field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise invalid_request("field %s must be >= %s" % (field, minimum))
    return val


def require_enum(payload, field, allowed):
    val = require_field(payload, field)
    if val not in allowed:
        raise invalid_request("field %s must be one of %s" % (field, sorted(allowed)))
    return val


def optional_enum(payload, field, allowed, default):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if val not in allowed:
        raise invalid_request("field %s must be one of %s" % (field, sorted(allowed)))
    return val


def optional_str(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if not isinstance(val, str):
        raise invalid_request("field %s must be a string" % field)
    return val
