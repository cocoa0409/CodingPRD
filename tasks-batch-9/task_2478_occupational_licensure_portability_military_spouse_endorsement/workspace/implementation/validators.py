"""Request-shape validation (PRD §2.8 check 3 -> ERR_INVALID_REQUEST, 400)."""
import re

from flask import request

import clock
from errors import invalid
from numbers_util import dec, rhu

UPPER_CODE_RE = re.compile(r"^[A-Z0-9_]+$")
TWO_LETTER_RE = re.compile(r"^[A-Z]{2}$")
PROFESSION_CODE_RE = re.compile(r"^[A-Z]{2,8}$")


def body():
    """Parse the JSON body; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        invalid("The request body is not valid JSON.")
    if not isinstance(data, dict):
        invalid("The request body must be a JSON object.")
    return data


def _fetch(payload, name, required):
    """Return (present, value); a missing required field is an invalid request."""
    if name not in payload or payload[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return False, None
    return True, payload[name]


def f_string(payload, name, required=True, default=None, pattern=None,
             allow_empty=False):
    present, value = _fetch(payload, name, required)
    if not present:
        return default
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        invalid("Field '%s' must be a non-empty string." % name)
    if pattern is not None and not pattern.match(value):
        invalid("Field '%s' is malformed." % name)
    return value


def f_bool(payload, name, required=True, default=None):
    present, value = _fetch(payload, name, required)
    if not present:
        return default
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def f_int(payload, name, required=True, default=None, minimum=None,
          maximum=None):
    present, value = _fetch(payload, name, required)
    if not present:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be at most %s." % (name, maximum))
    return value


def f_number(payload, name, required=True, default=None, minimum=None,
             maximum=None, places=2, exclusive_minimum=None):
    present, value = _fetch(payload, name, required)
    if not present:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % name)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        invalid("Field '%s' must be at least %s." % (name, minimum))
    if exclusive_minimum is not None and number <= dec(exclusive_minimum):
        invalid("Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if maximum is not None and number > dec(maximum):
        invalid("Field '%s' must be at most %s." % (name, maximum))
    return rhu(number, places)


def f_enum(payload, name, members, required=True, default=None):
    present, value = _fetch(payload, name, required)
    if not present:
        return default
    if not isinstance(value, str) or value not in members:
        invalid("Field '%s' must be one of: %s." % (name, ", ".join(members)))
    return value


def f_datetime(payload, name, required=True, default=None):
    present, value = _fetch(payload, name, required)
    if not present:
        return default
    parsed = clock.parse_iso8601(value)
    if parsed is None:
        invalid("Field '%s' must be a well-formed ISO 8601 UTC instant." % name)
    return parsed


def f_code_array(payload, name, required=True, default=None, min_items=0,
                 max_items=12):
    present, value = _fetch(payload, name, required)
    if not present:
        return list(default) if default is not None else None
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % name)
    if len(value) < min_items or len(value) > max_items:
        invalid("Field '%s' must contain between %d and %d entries."
                % (name, min_items, max_items))
    seen = set()
    for item in value:
        if not isinstance(item, str) or not UPPER_CODE_RE.match(item):
            invalid("Field '%s' must contain uppercase codes only." % name)
        if item in seen:
            invalid("Field '%s' must contain unique codes." % name)
        seen.add(item)
    return list(value)
