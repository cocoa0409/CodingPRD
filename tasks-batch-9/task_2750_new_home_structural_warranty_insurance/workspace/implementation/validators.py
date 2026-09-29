"""Request-shape validation (PRD 2.8 rung 8 -> ERR_INVALID_REQUEST)."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MISSING = object()


def body():
    """Parsed JSON object body; a missing/unparseable/non-object body behaves as
    an empty object so that the required-field checks produce the error."""
    try:
        parsed = request.get_json(silent=True, force=True)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    return {}


def _present(b, name):
    return name in b and b[name] is not None


def _require_present(b, name):
    if not _present(b, name):
        raise invalid("field '%s' is required" % name)
    return b[name]


# --- strings ---------------------------------------------------------------

def _check_str(name, value, min_len, max_len, non_blank):
    if not isinstance(value, str):
        raise invalid("field '%s' must be a string" % name)
    if non_blank and value.strip() == "":
        raise invalid("field '%s' must not be blank" % name)
    if min_len is not None and len(value) < min_len:
        raise invalid("field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("field '%s' must be at most %d characters" % (name, max_len))
    return value


def req_str(b, name, min_len=None, max_len=None, non_blank=True):
    return _check_str(name, _require_present(b, name), min_len, max_len, non_blank)


def opt_str(b, name, min_len=None, max_len=None, non_blank=True, default=None):
    if not _present(b, name):
        return default
    return _check_str(name, b[name], min_len, max_len, non_blank)


# --- integers --------------------------------------------------------------

def _check_int(name, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("field '%s' must be an integer" % name)
    if lo is not None and value < lo:
        raise invalid("field '%s' must be at least %d" % (name, lo))
    if hi is not None and value > hi:
        raise invalid("field '%s' must be at most %d" % (name, hi))
    return value


def req_int(b, name, lo=None, hi=None):
    return _check_int(name, _require_present(b, name), lo, hi)


def opt_int(b, name, lo=None, hi=None, default=None):
    if not _present(b, name):
        return default
    return _check_int(name, b[name], lo, hi)


# --- booleans --------------------------------------------------------------

def req_bool(b, name):
    value = _require_present(b, name)
    if not isinstance(value, bool):
        raise invalid("field '%s' must be a boolean" % name)
    return value


def opt_bool(b, name, default=None):
    if not _present(b, name):
        return default
    value = b[name]
    if not isinstance(value, bool):
        raise invalid("field '%s' must be a boolean" % name)
    return value


# --- enums -----------------------------------------------------------------

def req_enum(b, name, allowed):
    value = _require_present(b, name)
    if not isinstance(value, str) or value not in allowed:
        raise invalid("field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(b, name, allowed, default=None):
    if not _present(b, name):
        return default
    return req_enum(b, name, allowed)


# --- decimals / rates ------------------------------------------------------

def _as_decimal(name, value, places):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("field '%s' must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise invalid("field '%s' must be a number" % name)
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int):
        raise invalid("field '%s' must be a number" % name)
    if -exponent > places:
        raise invalid("field '%s' accepts at most %d decimal places" % (name, places))
    return dec


def req_rate(b, name, lo, hi, places):
    dec = _as_decimal(name, _require_present(b, name), places)
    if dec < Decimal(str(lo)) or dec > Decimal(str(hi)):
        raise invalid("field '%s' must be between %s and %s inclusive" % (name, lo, hi))
    return dec


# --- dates and instants ----------------------------------------------------

def parse_date_str(name, value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise invalid("field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % name)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise invalid("field '%s' must be a valid calendar date" % name)


def req_date(b, name):
    return parse_date_str(name, _require_present(b, name))


def opt_date(b, name, default=None):
    if not _present(b, name):
        return default
    return parse_date_str(name, b[name])


def parse_instant_str(name, value):
    if not isinstance(value, str):
        raise invalid("field '%s' must be an ISO 8601 UTC instant" % name)
    text = value.strip()
    if text == "":
        raise invalid("field '%s' must be an ISO 8601 UTC instant" % name)
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("field '%s' must be an ISO 8601 UTC instant" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(b, name):
    return parse_instant_str(name, _require_present(b, name))


def req_string_array(b, name, allowed, max_items):
    value = _require_present(b, name)
    if not isinstance(value, list):
        raise invalid("field '%s' must be an array" % name)
    if len(value) > max_items:
        raise invalid("field '%s' accepts at most %d entries" % (name, max_items))
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid("field '%s' entries must be one of %s"
                          % (name, ", ".join(sorted(allowed))))
        if item in seen:
            raise invalid("field '%s' must not contain duplicate entries" % name)
        seen.add(item)
    return list(value)


def fmt_date(value):
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)
