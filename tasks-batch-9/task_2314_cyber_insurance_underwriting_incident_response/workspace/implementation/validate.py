"""Schema validation helpers -- every failure raises ERR_INVALID_REQUEST (400)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from db import dec
from errors import bad_request

MISSING = object()


def body():
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise bad_request("request body must be a JSON object")
    if not isinstance(parsed, dict):
        raise bad_request("request body must be a JSON object")
    return parsed


def present(payload, name):
    return name in payload and payload[name] is not None


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def req_str(payload, name, min_len=1, max_len=None):
    if name not in payload or payload[name] is None:
        raise bad_request("%s is required" % name)
    value = payload[name]
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s must be at most %d characters" % (name, max_len))
    return value


def opt_str(payload, name, min_len=1, max_len=None, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_str(payload, name, min_len, max_len)


def req_enum(payload, name, domain):
    value = req_str(payload, name, min_len=1)
    if value not in domain:
        raise bad_request("%s must be one of %s" % (name, ", ".join(sorted(domain))))
    return value


def opt_enum(payload, name, domain, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_enum(payload, name, domain)


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------

def _to_decimal(name, value):
    if isinstance(value, bool):
        raise bad_request("%s must be a number" % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return dec(value)
        except (InvalidOperation, ValueError):
            raise bad_request("%s must be a number" % name)
    raise bad_request("%s must be a number" % name)


def _check_num(name, value, minimum, maximum, exclusive_min, exclusive_max, money):
    if minimum is not None:
        if exclusive_min and value <= minimum:
            raise bad_request("%s must be greater than %s" % (name, minimum))
        if not exclusive_min and value < minimum:
            raise bad_request("%s must be at least %s" % (name, minimum))
    if maximum is not None:
        if exclusive_max and value >= maximum:
            raise bad_request("%s must be less than %s" % (name, maximum))
        if not exclusive_max and value > maximum:
            raise bad_request("%s must be at most %s" % (name, maximum))
    if money:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise bad_request("%s must have at most 2 decimal places" % name)
    return value


def req_num(payload, name, minimum=None, maximum=None, exclusive_min=False,
            exclusive_max=False, money=False):
    if name not in payload or payload[name] is None:
        raise bad_request("%s is required" % name)
    value = _to_decimal(name, payload[name])
    return _check_num(name, value, minimum, maximum, exclusive_min, exclusive_max, money)


def opt_num(payload, name, minimum=None, maximum=None, exclusive_min=False,
            exclusive_max=False, money=False, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_num(payload, name, minimum, maximum, exclusive_min, exclusive_max, money)


def req_int(payload, name, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        raise bad_request("%s is required" % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at most %d" % (name, maximum))
    return value


def opt_int(payload, name, minimum=None, maximum=None, default=None):
    if name not in payload or payload[name] is None:
        return default
    return req_int(payload, name, minimum, maximum)


def req_bool(payload, name, default=None):
    if name not in payload or payload[name] is None:
        if default is None:
            raise bad_request("%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % name)
    return value


# --------------------------------------------------------------------------
# datetimes
# --------------------------------------------------------------------------

def parse_dt(name, value):
    if not isinstance(value, str) or not value.strip():
        raise bad_request("%s must be an ISO 8601 UTC timestamp" % name)
    text = value.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise bad_request("%s must be an ISO 8601 UTC timestamp" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(payload, name):
    if name not in payload or payload[name] is None:
        raise bad_request("%s is required" % name)
    return payload[name], parse_dt(name, payload[name])


def opt_dt(payload, name):
    if name not in payload or payload[name] is None:
        return None, None
    return req_dt(payload, name)


# --------------------------------------------------------------------------
# arrays
# --------------------------------------------------------------------------

def req_array(payload, name, domain=None, non_empty=True, unique=True):
    if name not in payload or payload[name] is None:
        raise bad_request("%s is required" % name)
    value = payload[name]
    if not isinstance(value, list):
        raise bad_request("%s must be an array" % name)
    if non_empty and len(value) == 0:
        raise bad_request("%s must not be empty" % name)
    for entry in value:
        if not isinstance(entry, str):
            raise bad_request("%s entries must be strings" % name)
        if domain is not None and entry not in domain:
            raise bad_request("%s entries must be one of %s" % (name, ", ".join(sorted(domain))))
    if unique and len(set(value)) != len(value):
        raise bad_request("%s must not contain duplicates" % name)
    return value


def opt_array(payload, name, domain=None, non_empty=False, default=None, unique=True):
    if name not in payload or payload[name] is None:
        return default if default is not None else []
    return req_array(payload, name, domain, non_empty, unique)


def req_object_array(payload, name, non_empty=True):
    if name not in payload or payload[name] is None:
        raise bad_request("%s is required" % name)
    value = payload[name]
    if not isinstance(value, list):
        raise bad_request("%s must be an array" % name)
    if non_empty and len(value) == 0:
        raise bad_request("%s must not be empty" % name)
    for entry in value:
        if not isinstance(entry, dict):
            raise bad_request("%s entries must be objects" % name)
    return value
