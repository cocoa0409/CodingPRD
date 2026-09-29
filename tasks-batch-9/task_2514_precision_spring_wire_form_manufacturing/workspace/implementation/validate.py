"""Request body / query validation.  Every failure here is rank 4:
ERR_INVALID_REQUEST (HTTP 400).
"""

from flask import request

import store
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body.  An absent body is treated as {}."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_string(payload, name, min_len=None, max_len=None):
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str) or not value.strip():
        bad("%s must be a non-empty string." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def req_enum(payload, name, allowed):
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_int(payload, name, minimum=None, maximum=None, gt=None):
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    _bounds(name, value, minimum, maximum, gt)
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None, gt=None):
    if not _present(payload, name):
        return default
    return req_int(payload, name, minimum=minimum, maximum=maximum, gt=gt)


def req_number(payload, name, minimum=None, maximum=None, gt=None):
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    _bounds(name, value, minimum, maximum, gt)
    return float(value)


def opt_number(payload, name, default=None, minimum=None, maximum=None, gt=None):
    if not _present(payload, name):
        return default
    return req_number(payload, name, minimum=minimum, maximum=maximum, gt=gt)


def _bounds(name, value, minimum, maximum, gt):
    if gt is not None and not value > gt:
        bad("%s must be greater than %s." % (name, gt))
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (name, maximum))


def req_bool(payload, name):
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    return req_bool(payload, name)


def req_id(payload, name):
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str) or not value.strip():
        bad("%s must be a non-empty string identifier." % name)
    return value


def opt_id(payload, name, default=None):
    if not _present(payload, name):
        return default
    return req_id(payload, name)


def req_measurements(payload, name="measurements"):
    """An array of numbers.  Typing failures are rank 4; a too-short array is
    rank 54 and therefore handled by the caller, not here."""
    if not _present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, list) or not value:
        bad("%s must be a non-empty array of numbers." % name)
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            bad("%s must contain only numbers." % name)
        out.append(float(item))
    return out


def req_datetime(payload, name):
    if not _present(payload, name):
        bad("%s is required." % name)
    raw = payload[name]
    if not isinstance(raw, str):
        bad("%s must be an ISO 8601 UTC timestamp string." % name)
    parsed = store.parse_iso8601(raw)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC timestamp string." % name)
    return parsed, raw


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def reject_version_fields(payload, *permitted):
    """PRD 2.7: no endpoint other than the three OCC writers accepts a version
    field.  Kept lenient: unknown extra fields are ignored."""
    return payload
