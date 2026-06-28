"""Request-body validation helpers (PRD §2.8 priority 4 / ERR_INVALID_REQUEST).

These enforce presence, type, enum-domain, and integer-range constraints. A
malformed, incomplete, mistyped, or out-of-range body yields ERR_INVALID_REQUEST.
Percentage out-of-range is a separate ERR_VALIDATION_RANGE (priority handled in
the route after the body shape is validated).
"""
import errors


def require_body(body):
    if body is None or not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def req_str(body, field):
    if field not in body:
        raise errors.invalid_request("Missing required field: " + field)
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field must be a non-empty string: " + field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request("Field must be a string: " + field)
    return val


def _is_int(val):
    # Reject bool (a subclass of int) and floats.
    return isinstance(val, int) and not isinstance(val, bool)


def req_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise errors.invalid_request("Missing required field: " + field)
    val = body[field]
    if not _is_int(val):
        raise errors.invalid_request("Field must be an integer: " + field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field below minimum: " + field)
    if maximum is not None and val > maximum:
        raise errors.invalid_request("Field above maximum: " + field)
    return val


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_enum(body, field, domain):
    val = req_str(body, field)
    if val not in domain:
        raise errors.invalid_request("Field out of enum domain: " + field)
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + field)
    return val


def req_number(body, field):
    """Accepts int or float (used for percentage fields and to surface
    presence/type errors before the range check)."""
    if field not in body:
        raise errors.invalid_request("Missing required field: " + field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field must be a number: " + field)
    return val


def opt_pct(body, field, default, lo, hi):
    """Percentage field: optional, defaulting; type error -> ERR_INVALID_REQUEST,
    range error -> ERR_VALIDATION_RANGE (PRD §2.8 last paragraph / §3.2)."""
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field must be a number: " + field)
    if val < lo or val > hi:
        raise errors.validation_range("Percentage out of range: " + field)
    return float(val)
