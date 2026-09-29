"""Request-shape validation: priority 5 of the rejection ladder.

Every failure here raises ERR_INVALID_REQUEST with HTTP 400.
"""

import re

from flask import request

from errors import ERR_INVALID_REQUEST, fail
from timeutil import parse_date, parse_iso_ms

FOUR_DIGITS = re.compile(r"^\d{4}$")
SIX_DIGITS = re.compile(r"^\d{6}$")
TWO_UPPER = re.compile(r"^[A-Z]{2}$")
THREE_UPPER = re.compile(r"^[A-Z]{3}$")
UPPER_KEY = re.compile(r"^[A-Z_]{1,40}$")
QUARTER_LABEL = re.compile(r"^20[0-9]{2}Q[1-4]$")


def bad(message):
    fail(ERR_INVALID_REQUEST, message)


def body():
    """The JSON request body as a dict; a missing body is treated as {}."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def raw_id(data, name):
    """A body foreign key as supplied, for priority-4 resolution.

    Only a non-empty string is resolvable; anything else falls through to the
    request-shape check at priority 5.
    """
    value = data.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None


def req_present(data, name):
    if name not in data or data.get(name) is None:
        bad("Field '%s' is required." % name)
    return data[name]


def req_str(data, name, min_len=1, max_len=None):
    value = req_present(data, name)
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, min_len=0, max_len=None, default=None):
    if name not in data or data.get(name) is None:
        return default
    return req_str(data, name, min_len, max_len)


def req_int(data, name, minimum=None, maximum=None):
    value = req_present(data, name)
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def req_bool(data, name):
    value = req_present(data, name)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=False):
    if name not in data or data.get(name) is None:
        return default
    return req_bool(data, name)


def req_enum(data, name, domain):
    value = req_present(data, name)
    if not isinstance(value, str) or value not in domain:
        bad("Field '%s' must be one of %s." % (name, ", ".join(domain)))
    return value


def req_ts(data, name):
    value = req_present(data, name)
    ms = parse_iso_ms(value)
    if ms is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % name)
    return ms


def req_date(data, name):
    value = req_present(data, name)
    if parse_date(value) is None:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return value.strip()


def req_number(data, name, minimum=None, maximum=None, max_places=None,
               exclusive_min=False):
    value = req_present(data, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    if exclusive_min and minimum is not None and not value > minimum:
        bad("Field '%s' must be greater than %s." % (name, minimum))
    if not exclusive_min and minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    if max_places is not None:
        text = repr(float(value))
        if "e" in text or "E" in text:
            bad("Field '%s' has too many decimal places." % name)
        if "." in text and len(text.split(".", 1)[1].rstrip("0")) > max_places:
            bad("Field '%s' has at most %d decimal places." % (name, max_places))
    return value


def req_code_list(data, name, vocabulary=None, required=True, default=None,
                  pattern=None, non_empty=False):
    """A duplicate-free list of string tokens."""
    if name not in data or data.get(name) is None:
        if required:
            bad("Field '%s' is required." % name)
        return list(default or [])
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    out = []
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must contain only strings." % name)
        if vocabulary is not None and item not in vocabulary:
            bad("Field '%s' contains the unknown token '%s'." % (name, item))
        if pattern is not None and not pattern.match(item):
            bad("Field '%s' contains the malformed value '%s'." % (name, item))
        if item in out:
            bad("Field '%s' must not contain duplicates." % name)
        out.append(item)
    if non_empty and not out:
        bad("Field '%s' must not be empty." % name)
    return out


def req_mcc(data, name):
    value = req_str(data, name, 1, None)
    if not FOUR_DIGITS.match(value):
        bad("Field '%s' must be exactly four digits." % name)
    return value


def req_currency(data, name):
    value = req_str(data, name, 1, None)
    if not THREE_UPPER.match(value):
        bad("Field '%s' must be exactly three uppercase letters." % name)
    return value


def req_country(data, name):
    value = req_str(data, name, 1, None)
    if not TWO_UPPER.match(value):
        bad("Field '%s' must be exactly two uppercase letters." % name)
    return value


def req_business_type_key(data, name):
    value = req_str(data, name, 1, 40)
    if not UPPER_KEY.match(value):
        bad("Field '%s' must be uppercase A-Z and underscore." % name)
    return value
