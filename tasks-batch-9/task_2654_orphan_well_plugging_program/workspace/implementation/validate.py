"""Schema validation helpers (PRD 2.10 step 7 -> ERR_INVALID_REQUEST)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid
from store import parse_iso

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
REGION_RE = re.compile(r"^[A-Z]{2}$")

_MISSING = object()


def body():
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def _get(data, name, required):
    if name not in data or data[name] is None:
        if required:
            raise invalid("%s is required." % name)
        return _MISSING
    return data[name]


def str_field(data, name, required=True, allow_empty=False, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise invalid("%s must be a string." % name)
    if not allow_empty and value.strip() == "":
        raise invalid("%s must be a non-empty string." % name)
    return value


def region_field(data, name, required=True, default=None):
    value = str_field(data, name, required=required, default=_MISSING)
    if value is _MISSING:
        return default
    if not REGION_RE.match(value):
        raise invalid("%s must be exactly two uppercase letters." % name)
    return value


def int_field(data, name, required=True, minimum=None, maximum=None,
              exclusive_minimum=None, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer." % name)
    return _bounds(name, value, minimum, maximum, exclusive_minimum)


def num_field(data, name, required=True, minimum=None, maximum=None,
              exclusive_minimum=None, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("%s must be a number." % name)
    return _bounds(name, value, minimum, maximum, exclusive_minimum)


def _bounds(name, value, minimum, maximum, exclusive_minimum):
    if minimum is not None and value < minimum:
        raise invalid("%s must be >= %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise invalid("%s must be > %s." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be <= %s." % (name, maximum))
    return value


def decimal_field(data, name, required=True, minimum=None, maximum=None,
                  exclusive_minimum=None, default=None):
    value = num_field(data, name, required=required, minimum=minimum,
                      maximum=maximum, exclusive_minimum=exclusive_minimum,
                      default=_MISSING)
    if value is _MISSING:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise invalid("%s must be a number." % name)


def enum_field(data, name, allowed, required=True, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def month_field(data, name, required=True, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not MONTH_RE.match(value):
        raise invalid("%s must be a YYYY-MM month string." % name)
    return value


def date_field(data, name, required=True, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise invalid("%s must be a YYYY-MM-DD date string." % name)
    return value


def datetime_field(data, name, required=True, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise invalid("%s must be an ISO 8601 timestamp string." % name)
    try:
        return parse_iso(value)
    except ValueError:
        raise invalid("%s must be a valid ISO 8601 timestamp." % name)


def array_field(data, name, required=True, allow_empty=False, default=None):
    value = _get(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        raise invalid("%s must be an array." % name)
    if not allow_empty and len(value) == 0:
        raise invalid("%s must be a non-empty array." % name)
    return value


def enum_array_field(data, name, allowed, required=True, allow_empty=False,
                     default=None):
    value = array_field(data, name, required=required, allow_empty=allow_empty,
                        default=_MISSING)
    if value is _MISSING:
        return default
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid(
                "%s entries must each be one of %s."
                % (name, ", ".join(sorted(allowed)))
            )
    return value


def id_field(data, name, required=True, default=None):
    return str_field(data, name, required=required, default=default)
