"""Request-shape validation (PRD 2.9 step 5) -> ERR_INVALID_REQUEST (400).

Computed and system-managed fields that appear in a request body are silently
ignored rather than rejected, so nothing here inspects unknown keys.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from calc import D
from errors import ApiError

_MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """The request body as a dict; a non-object body is a shape error."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


def raw(body, key):
    return body.get(key, _MISSING)


def present(body, key):
    value = body.get(key, _MISSING)
    return value is not _MISSING and value is not None


def opt_str_id(body, key):
    """Raw foreign-key read used before shape validation (PRD 2.9 step 4)."""
    value = body.get(key, _MISSING)
    if value is _MISSING or not isinstance(value, str):
        return None
    return value


def string(body, key, min_len=1, max_len=None, required=True, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return default
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def enum(body, key, values, required=True, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return default
    if not isinstance(value, str) or value not in values:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(values)))
    return value


def integer(body, key, minimum=None, maximum=None, required=True, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %s." % (key, maximum))
    return value


def number(body, key, minimum=None, maximum=None, dp=2, exclusive_min=False,
           required=True, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    try:
        dec = D(value)
    except (InvalidOperation, ValueError):
        raise bad("Field '%s' must be a number." % key)
    if not dec.is_finite():
        raise bad("Field '%s' must be a finite number." % key)
    exponent = dec.normalize().as_tuple().exponent
    if exponent < -dp:
        raise bad("Field '%s' accepts at most %d decimal places." % (key, dp))
    if minimum is not None:
        if exclusive_min and dec <= D(minimum):
            raise bad("Field '%s' must be greater than %s." % (key, minimum))
        if not exclusive_min and dec < D(minimum):
            raise bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and dec > D(maximum):
        raise bad("Field '%s' must be at most %s." % (key, maximum))
    return dec.quantize(Decimal(1).scaleb(-dp)) if dp is not None else dec


def date_field(body, key, required=True, default=None):
    """A YYYY-MM-DD calendar date; returns (raw_string, date)."""
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return default, None
    if not isinstance(value, str) or len(value) != 10:
        raise bad("Field '%s' must be a YYYY-MM-DD date." % key)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return value, parsed


def parse_instant(value, key):
    if not isinstance(value, str):
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_field(body, key, required=True):
    """An ISO 8601 instant; returns (raw_string, aware datetime)."""
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return None, None
    return value, parse_instant(value, key)
