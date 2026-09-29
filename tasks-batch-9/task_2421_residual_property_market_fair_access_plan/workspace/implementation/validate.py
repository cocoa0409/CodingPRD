"""Request-schema validation — rung 3 of the precedence ladder (PRD 2.11).

Required body fields present, enum members recognized, integers non-negative,
dates well-formed ISO-8601, condition scores 0..100, limit 1..100, offset >= 0,
evidence_reference a non-empty string.  Every failure here is
ERR_INVALID_REQUEST (400) and is raised before any identifier is resolved.
"""

from flask import request

from errors import invalid
from util import D, fmt_date, iso_ms, parse_date, parse_instant

_UNSET = object()


def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        invalid("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        invalid("Request body must be a JSON object")
    return parsed


def present(data, name):
    return name in data and data[name] is not None


# --- strings --------------------------------------------------------------

def req_string(data, name):
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        invalid("Field '%s' must be a non-empty string" % name)
    return value


def opt_string(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string" % name)
    return value


# --- integers -------------------------------------------------------------

def _int_value(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer" % name)
    return value


def req_int(data, name, minimum=0, maximum=None, positive=False):
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    value = _int_value(name, data[name])
    if positive and value <= 0:
        invalid("Field '%s' must be greater than 0" % name)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be at most %s" % (name, maximum))
    return value


def opt_int(data, name, default=None, minimum=0, maximum=None, positive=False):
    if not present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum, positive=positive)


# --- decimals / percentages ----------------------------------------------

def req_percent(data, name):
    """A decimal percentage in 0.00 .. 100.00 (PRD 2.5)."""
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    return _percent_value(name, data[name])


def opt_percent(data, name, default=None):
    if not present(data, name):
        return default
    return _percent_value(name, data[name])


def _percent_value(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number" % name)
    dec = D(value)
    if dec < D(0) or dec > D(100):
        invalid("Field '%s' must be between 0.00 and 100.00" % name)
    return dec


# --- enums, booleans -----------------------------------------------------

def req_enum(data, name, allowed):
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_bool(data, name):
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    value = data[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean" % name)
    return value


# --- temporal ------------------------------------------------------------

def req_date(data, name):
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    parsed = parse_date(data[name])
    if parsed is None:
        invalid("Field '%s' must be a date in YYYY-MM-DD form" % name)
    return parsed


def opt_date(data, name, default=None):
    if not present(data, name):
        return default
    return req_date(data, name)


def req_instant(data, name):
    if not present(data, name):
        invalid("Field '%s' is required" % name)
    parsed = parse_instant(data[name])
    if parsed is None:
        invalid("Field '%s' must be an ISO-8601 instant" % name)
    return parsed


# --- condition score -----------------------------------------------------

def req_score(data, name):
    return req_int(data, name, minimum=0, maximum=100)


# --- pagination and query filters ---------------------------------------

def pagination():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            invalid("Query parameter 'offset' must be at least 0")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    try:
        return int(text)
    except (TypeError, ValueError):
        invalid("Query parameter '%s' must be an integer" % name)


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        invalid("Query parameter '%s' must be one of %s"
                % (name, ", ".join(sorted(allowed))))
    return raw


def filter_string(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


# --- storage normalisation ----------------------------------------------

def store_date(value):
    return fmt_date(value) if value is not None else None


def store_instant(value):
    return iso_ms(value) if value is not None else None
