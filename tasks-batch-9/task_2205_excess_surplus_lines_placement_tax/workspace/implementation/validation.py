"""Rung 6 of the ladder: field shape (PRD 2.11 item 6).

Every helper here raises ERR_INVALID_REQUEST (400). Callers invoke them in the
field order the endpoint declares, so the first malformed field is the one
reported.
"""

import re

from flask import request

import clock
from errors import ApiError

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body. A malformed or non-object body reads as empty.

    Rung 5 (body FK existence) precedes rung 6 (field shape), so an
    unparseable body simply yields no resolvable foreign keys and then trips
    the required-field checks of rung 6.
    """
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def present(data, name):
    return name in data and data.get(name) is not None


def fk_value(data, name):
    """A body FK candidate for rung 5: only well-formed strings are resolved."""
    value = data.get(name, None)
    if isinstance(value, str) and value != "":
        return value
    return None


# --- strings --------------------------------------------------------------

def req_str(data, name, max_len=None, allow_blank=False):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if not allow_blank and value.strip() == "":
        bad("%s must be a non-empty string." % name)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, default=None, max_len=None, allow_blank=False):
    if not present(data, name):
        return default
    return req_str(data, name, max_len=max_len, allow_blank=allow_blank)


def req_state_code(data, name):
    value = req_str(data, name)
    if not STATE_CODE_RE.match(value):
        bad("%s must be exactly two uppercase ASCII letters." % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


# --- numbers --------------------------------------------------------------

def _as_int(name, value):
    if isinstance(value, bool):
        bad("%s must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad("%s must be an integer." % name)


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    value = _as_int(name, value)
    if minimum is not None and value < minimum:
        bad("%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %d." % (name, maximum))
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None, nullable=False):
    if name not in data:
        return default
    if data.get(name) is None:
        if nullable:
            return None
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def _as_number(name, value):
    if isinstance(value, bool):
        bad("%s must be a number." % name)
    if isinstance(value, (int, float)):
        return value
    bad("%s must be a number." % name)


def _decimals(value):
    text = repr(float(value)) if isinstance(value, float) else str(value)
    if "e" in text or "E" in text:
        return 99
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1].rstrip("0"))


def req_number(data, name, minimum=None, maximum=None, max_decimals=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    value = _as_number(name, value)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (name, maximum))
    if max_decimals is not None and _decimals(value) > max_decimals:
        bad("%s must carry at most %d decimal places." % (name, max_decimals))
    return value


def opt_number(data, name, default=None, minimum=None, maximum=None,
               max_decimals=None):
    if not present(data, name):
        return default
    return req_number(data, name, minimum=minimum, maximum=maximum,
                      max_decimals=max_decimals)


# --- booleans -------------------------------------------------------------

def req_bool(data, name):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(data, name, default=False):
    if not present(data, name):
        return default
    return req_bool(data, name)


# --- datetimes ------------------------------------------------------------

def req_datetime(data, name):
    """Returns (aware datetime, raw string as supplied)."""
    value = req_str(data, name)
    parsed = clock.parse(value)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant." % name)
    return parsed, value


def opt_datetime(data, name):
    if not present(data, name):
        return None, None
    return req_datetime(data, name)


# --- arrays ---------------------------------------------------------------

def req_array(data, name, allow_empty=True):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if not allow_empty and len(value) == 0:
        bad("%s must be a non-empty array." % name)
    return value


def req_code_array(data, name):
    values = req_array(data, name)
    out = []
    for item in values:
        if not isinstance(item, str) or item.strip() == "":
            bad("%s must contain non-empty strings." % name)
        out.append(item)
    return out


def req_upper_code_array(data, name):
    values = req_code_array(data, name)
    for item in values:
        if item != item.upper():
            bad("%s must contain uppercase codes." % name)
    return values


def req_state_exposures(data, name):
    """`state_exposures`: array of {state_code, insured_value_cents}.

    An *absent* array is a rung-6 shape failure (ERR_INVALID_REQUEST), but an
    *empty* array is not: PRD 3.3 makes it the first step of the home-state
    waterfall and refuses it "outright with ERR_HOME_STATE_INDETERMINATE".
    """
    rows = req_array(data, name, allow_empty=True)
    seen = set()
    out = []
    for row in rows:
        if not isinstance(row, dict):
            bad("%s entries must be objects." % name)
        code = row.get("state_code", None)
        if not isinstance(code, str) or not STATE_CODE_RE.match(code):
            bad("%s[].state_code must be exactly two uppercase ASCII letters."
                % name)
        if code in seen:
            bad("%s[].state_code must be unique within the array." % name)
        seen.add(code)
        value = row.get("insured_value_cents", _MISSING)
        if value is _MISSING or value is None:
            bad("%s[].insured_value_cents is required." % name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or (isinstance(value, float) and not float(value).is_integer()):
            bad("%s[].insured_value_cents must be an integer." % name)
        value = int(value)
        if value < 0:
            bad("%s[].insured_value_cents must be >= 0." % name)
        out.append({"state_code": code, "insured_value_cents": value})
    return out
