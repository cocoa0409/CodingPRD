"""Band 4 request-shape validation.  Every failure is ERR_INVALID_REQUEST."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from numeric import dec
from store import parse_dt

MISSING = object()


def body():
    """The JSON request body as a dict.  A non-object body is malformed."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        data = None
    if not isinstance(data, dict):
        # A non-object body carries no fields, so the missing-required-field rung
        # of the shape band reports it -- reading the body is not itself a check.
        return {}
    return data


def _present(data, key):
    return key in data and data[key] is not None


def raw(data, key):
    if key not in data:
        return MISSING
    return data[key]


# --------------------------------------------------------------------------- #
# strings
# --------------------------------------------------------------------------- #
def req_str(data, key, min_len=None):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST")
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST")
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST")
    return value


def opt_str(data, key, min_len=None, default=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len)


# --------------------------------------------------------------------------- #
# integers
# --------------------------------------------------------------------------- #
def _as_int(value):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    fail("ERR_INVALID_REQUEST")


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST")
    value = _as_int(data[key])
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST")
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST")
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum, maximum)


# --------------------------------------------------------------------------- #
# decimals
# --------------------------------------------------------------------------- #
def _as_dec(value, places):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST")
    if isinstance(value, (int, float, Decimal)):
        try:
            return dec(value, places)
        except (InvalidOperation, ValueError):
            fail("ERR_INVALID_REQUEST")
    fail("ERR_INVALID_REQUEST")


def req_dec(data, key, places=2, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST")
    value = _as_dec(data[key], places)
    if minimum is not None and value < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST")
    if exclusive_min is not None and value <= Decimal(str(exclusive_min)):
        fail("ERR_INVALID_REQUEST")
    if maximum is not None and value > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST")
    return value


def opt_dec(data, key, places=2, minimum=None, maximum=None,
            exclusive_min=None, default=None):
    if not _present(data, key):
        return default
    return req_dec(data, key, places, minimum, maximum, exclusive_min)


# --------------------------------------------------------------------------- #
# booleans / enums / arrays / datetimes
# --------------------------------------------------------------------------- #
def req_bool(data, key):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST")
    value = data[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST")
    return value


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST")
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def opt_str_array(data, key, allowed=None, default=None):
    if not _present(data, key):
        return list(default) if default is not None else []
    value = data[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST")
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST")
        if allowed is not None and item not in allowed:
            fail("ERR_INVALID_REQUEST")
    return list(value)


def req_dt(data, key):
    value = req_str(data, key)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST")
    return value, parsed


def opt_dt(data, key):
    if not _present(data, key):
        return None, None
    return req_dt(data, key)


def opt_id(data, key):
    """An optional foreign-key reference: must be a string when supplied."""
    if not _present(data, key):
        return None
    value = data[key]
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST")
    return value


def body_id(data, key):
    """A foreign key whose absence is reported by the existence band, not here."""
    value = data.get(key)
    if isinstance(value, str) and value != "":
        return value
    return None
