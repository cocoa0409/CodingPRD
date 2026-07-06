"""Body well-formedness helpers (PRD §2.7 step 5 -> ERR_INVALID_REQUEST 400)."""
from errors import err, ERR_INVALID_REQUEST


def body_dict(payload):
    """Return the JSON body as a dict, or {} if absent. Reject non-objects."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return payload


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s." % (field, maximum))
    return val


def optional_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s." % (field, sorted(allowed)))
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return val


def optional_number(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number." % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s." % (field, maximum))
    return val
