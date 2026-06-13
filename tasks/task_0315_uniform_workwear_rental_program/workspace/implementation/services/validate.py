"""Body field validation helpers (priority 14: ERR_INVALID_REQUEST).

These raise ERR_INVALID_REQUEST for general well-formedness problems: missing
required fields, bad enums, out-of-range integers, malformed windows/slots.
Specific higher-priority or specialized errors (pagination, emblem text, soil
count) are raised by their dedicated checks elsewhere.
"""
import errors

SERVICE_DAYS = {"MON", "TUE", "WED", "THU", "FRI"}
SHIRT_SIZES = {"XS", "S", "M", "L", "XL", "XXL"}
GARMENT_CATEGORIES = {"SHIRT", "PANT", "JACKET", "COVERALL"}


def get_body():
    """Return the JSON body as a dict, or {} when absent. Bad JSON -> 400."""
    from flask import request
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body.")
    if data is None:
        # Body present but not valid JSON object.
        if request.data.strip():
            raise errors.invalid_request("Malformed JSON body.")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request("Field %s must be a non-blank string." % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s." % (field, sorted(allowed)))
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise errors.invalid_request("Field %s must be <= %s." % (field, maximum))
    return val


def optional_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum)


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string." % field)
    return val
