"""Request shape validation (PRD 2.6 / validation priority 3).

Every failure in this module is ERR_INVALID_REQUEST (422). Shape is checked
before existence and before any state guard, but strictly after authentication
and authorisation -- see PRD 2.9.
"""

from flask import request

from calc import parse_date
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict. A missing body is an empty object."""
    raw = request.get_json(silent=True)
    if raw is None:
        if request.data and request.data.strip():
            bad("request body must be a JSON object")
        return {}
    if not isinstance(raw, dict):
        bad("request body must be a JSON object")
    return raw


def _present(data, key):
    return key in data and data[key] is not None


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def req_str(data, key, min_len=1, max_len=None, non_blank=True):
    if not _present(data, key):
        bad("%s is required" % key)
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if non_blank and not value.strip():
        bad("%s must not be blank" % key)
    if min_len is not None and len(value) < min_len:
        bad("%s is too short" % key)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long" % key)
    return value


def opt_str(data, key, min_len=0, max_len=None, default=None, non_blank=False):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len=min_len, max_len=max_len, non_blank=non_blank)


def req_enum(data, key, allowed):
    value = req_str(data, key, min_len=1)
    if value not in allowed:
        bad("%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_country(data, key):
    value = req_str(data, key, min_len=2, max_len=2)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("%s must be exactly two uppercase letters" % key)
    return value


def opt_country(data, key, default=""):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if value == "":
        return ""
    return req_country(data, key)


def req_currency(data, key):
    value = req_str(data, key, min_len=3, max_len=3)
    if len(value) != 3 or not value.isalpha() or value != value.upper():
        bad("%s must be exactly three uppercase letters" % key)
    return value


def req_digits(data, key, length):
    value = req_str(data, key, min_len=length, max_len=length)
    if not value.isdigit() or len(value) != length:
        bad("%s must be exactly %d digits" % (key, length))
    return value


def opt_hs_code(data, key, default=""):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if value == "":
        return ""
    if not value.isdigit() or not (6 <= len(value) <= 10):
        bad("%s must be empty or 6 to 10 digits" % key)
    return value


def req_date(data, key):
    value = req_str(data, key, min_len=10, max_len=10)
    if parse_date(value) is None:
        bad("%s must be a valid YYYY-MM-DD date" % key)
    return value


def opt_date(data, key, default=None):
    if not _present(data, key):
        return default
    return req_date(data, key)


def req_instant(data, key):
    from db import parse_instant
    value = req_str(data, key, min_len=1)
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be a valid ISO 8601 instant" % key)
    return parsed


# --------------------------------------------------------------------------
# numbers and booleans
# --------------------------------------------------------------------------

def _as_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad("%s is required" % key)
    value = _as_int(key, data[key])
    if minimum is not None and value < minimum:
        bad("%s must be at least %d" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d" % (key, maximum))
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_bool(data, key):
    if not _present(data, key):
        bad("%s is required" % key)
    if not isinstance(data[key], bool):
        bad("%s must be a boolean" % key)
    return data[key]


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_id(data, key):
    return req_str(data, key, min_len=1, max_len=200)


def req_str_array(data, key, min_items=1, max_items=None, no_duplicates=True, item_len=None):
    if not _present(data, key):
        bad("%s is required" % key)
    value = data[key]
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    if min_items is not None and len(value) < min_items:
        bad("%s must carry at least %d element(s)" % (key, min_items))
    if max_items is not None and len(value) > max_items:
        bad("%s must carry at most %d element(s)" % (key, max_items))
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("%s elements must be non-blank strings" % key)
        if item_len is not None and len(item) != item_len:
            bad("%s elements must be %d characters" % (key, item_len))
    if no_duplicates and len(set(value)) != len(value):
        bad("%s must not contain duplicates" % key)
    return value


def opt_code_array(data, key, default=None):
    """transit_country_codes: array of two-letter codes, empty by default."""
    if not _present(data, key):
        return list(default or [])
    value = data[key]
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    out = []
    for item in value:
        if not isinstance(item, str):
            bad("%s elements must be strings" % key)
        if len(item) != 2 or not item.isalpha() or item != item.upper():
            bad("%s elements must be exactly two uppercase letters" % key)
        out.append(item)
    return out


def req_object(data, key, min_keys=None, max_keys=None):
    if not _present(data, key):
        bad("%s is required" % key)
    value = data[key]
    if not isinstance(value, dict):
        bad("%s must be an object" % key)
    if min_keys is not None and len(value) < min_keys:
        bad("%s must carry at least %d key(s)" % (key, min_keys))
    if max_keys is not None and len(value) > max_keys:
        bad("%s must carry at most %d key(s)" % (key, max_keys))
    return value


# --------------------------------------------------------------------------
# query filters
# --------------------------------------------------------------------------

def arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def arg_bool(name):
    raw = arg(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s must be a boolean" % name)


def arg_int(name):
    raw = arg(name)
    if raw is None:
        return None
    try:
        return int(raw, 10)
    except (TypeError, ValueError):
        bad("%s must be an integer" % name)


def filtered(rows, **equals):
    """Drop rows that do not match every supplied non-None filter value."""
    out = rows
    for field, expected in equals.items():
        if expected is None:
            continue
        out = [row for row in out if row.get(field) == expected]
    return out
