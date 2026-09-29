"""Level 4 request-shape validation (PRD 2.10 item 4)."""

from flask import request

from errors import ApiError
from util import D, decimal_places, parse_iso

_MISSING = object()


def body():
    """The JSON payload; a malformed or absent body reads as an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return data


def fail(name, detail):
    raise ApiError("ERR_VALIDATION", "%s %s" % (name, detail))


def present(payload, name):
    return name in payload and payload[name] is not None


def _require(payload, name):
    if name not in payload or payload[name] is None:
        fail(name, "is required.")
    return payload[name]


def string_field(payload, name, required=True, min_len=None, max_len=None,
                 allow_empty=True, default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail(name, "must be a string.")
    if not allow_empty and value == "":
        fail(name, "must not be empty.")
    if min_len is not None and len(value) < min_len:
        fail(name, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        fail(name, "must be at most %d characters." % max_len)
    return value


def enum_field(payload, name, allowed, required=True, default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail(name, "must be one of %s." % ", ".join(allowed))
    return value


def _numeric(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(name, "must be a number.")
    return D(value)


def number_field(payload, name, required=True, gt=None, ge=None, le=None,
                 places=None, default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    value = _numeric(payload[name], name)
    if places is not None and decimal_places(value) > places:
        fail(name, "may carry at most %d decimal places." % places)
    if gt is not None and value <= D(gt):
        fail(name, "must be greater than %s." % gt)
    if ge is not None and value < D(ge):
        fail(name, "must be at least %s." % ge)
    if le is not None and value > D(le):
        fail(name, "must be at most %s." % le)
    return value


def int_field(payload, name, required=True, ge=None, le=None, allowed=None,
              default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(name, "must be an integer.")
    if allowed is not None and value not in allowed:
        fail(name, "must be one of %s." % ", ".join(str(a) for a in allowed))
    if ge is not None and value < ge:
        fail(name, "must be at least %d." % ge)
    if le is not None and value > le:
        fail(name, "must be at most %d." % le)
    return value


def datetime_field(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    parsed = parse_iso(payload[name])
    if parsed is None:
        fail(name, "must be a well-formed ISO 8601 UTC instant.")
    return parsed


def window_order(start, end):
    if start is not None and end is not None and not end > start:
        fail("window_end", "must be strictly after window_start.")


def step_sequence_field(payload, name="step_pct_sequence", required=True):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return None
    value = payload[name]
    if not isinstance(value, list) or not value:
        fail(name, "must be a non-empty array of integers.")
    if len(value) > 6:
        fail(name, "may carry at most six steps.")
    previous = None
    for step in value:
        if isinstance(step, bool) or not isinstance(step, int):
            fail(name, "must contain integers only.")
        if step < 1 or step > 100:
            fail(name, "steps must each lie between 1 and 100.")
        if previous is not None and step <= previous:
            fail(name, "must be strictly ascending.")
        previous = step
    if value[-1] != 100:
        fail(name, "must end at exactly 100.")
    return list(value)


def id_list_field(payload, name, required=False, default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    value = payload[name]
    if not isinstance(value, list):
        fail(name, "must be an array of identifiers.")
    for item in value:
        if not isinstance(item, str):
            fail(name, "must contain identifiers only.")
    return list(value)


def fk_field(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            fail(name, "is required.")
        return default
    value = payload[name]
    if not isinstance(value, str) or value == "":
        fail(name, "must be an identifier string.")
    return value


def optional_string_or_null(payload, name):
    """A field that may be written to a string or explicitly cleared to null."""
    if name not in payload:
        return _MISSING
    value = payload[name]
    if value is None:
        return None
    if not isinstance(value, str):
        fail(name, "must be a string.")
    return value


MISSING = _MISSING


def truthy(raw):
    return isinstance(raw, str) and raw.strip().lower() in ("1", "true", "yes")
