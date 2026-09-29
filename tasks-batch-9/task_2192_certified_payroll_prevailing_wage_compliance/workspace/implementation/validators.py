"""Body-shape and field-level validation (rung 7) plus FK resolution (rungs 3/4)."""

from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError

MISSING = object()


def body():
    """Parsed JSON object body; anything but an object is a shape violation."""
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def present(payload, name):
    return name in payload and payload[name] is not None


# ---------------------------------------------------------------------------
# FK resolution
# ---------------------------------------------------------------------------
def lookup(collection, identifier, error_id):
    if not isinstance(identifier, str) or identifier not in collection:
        raise ApiError(error_id, "Referenced resource does not exist.")
    return collection[identifier]


def resolve_fk(payload, name, collection, error_id):
    """Resolve an optional body foreign key. Missing/null returns None."""
    if not present(payload, name):
        return None
    return lookup(collection, payload[name], error_id)


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------
def req_string(payload, name, min_len=1, max_len=None, upper=False):
    if not present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    if upper and value != value.upper():
        bad("%s must be uppercase." % name)
    return value


def opt_string(payload, name, default=None, min_len=None, max_len=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def req_nonempty_string(payload, name):
    value = req_string(payload, name, min_len=1)
    if value.strip() == "":
        bad("%s must be non-empty." % name)
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        bad("%s is required." % name)
    value = _as_int(name, payload[name])
    _range_int(name, value, minimum, maximum)
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    value = _as_int(name, payload[name])
    _range_int(name, value, minimum, maximum)
    return value


def _range_int(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d." % (name, maximum))


def req_enum(payload, name, allowed):
    value = req_string(payload, name)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_bool(payload, name, default=None):
    if not present(payload, name):
        if default is None:
            bad("%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


# ---------------------------------------------------------------------------
# Hours -- two decimal places, exact Decimal storage
# ---------------------------------------------------------------------------
def _as_hours(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        bad("%s must be a number." % name)
    if -amount.as_tuple().exponent > 2:
        bad("%s must carry at most two decimal places." % name)
    return amount


def req_hours(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        bad("%s is required." % name)
    amount = _as_hours(name, payload[name])
    _range_dec(name, amount, minimum, maximum)
    return amount


def opt_hours(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    amount = _as_hours(name, payload[name])
    _range_dec(name, amount, minimum, maximum)
    return amount


def _range_dec(name, amount, minimum, maximum):
    if minimum is not None and amount < Decimal(str(minimum)):
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and amount > Decimal(str(maximum)):
        bad("%s must be at most %s." % (name, maximum))


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def req_instant(payload, name):
    if not present(payload, name):
        bad("%s is required." % name)
    parsed = db.parse_iso(payload[name])
    if parsed is None:
        bad("%s must be a parseable ISO 8601 timestamp." % name)
    return parsed


def opt_instant(payload, name, default=None):
    if not present(payload, name):
        return default
    parsed = db.parse_iso(payload[name])
    if parsed is None:
        bad("%s must be a parseable ISO 8601 timestamp." % name)
    return parsed


def req_int_array(payload, name, min_len, max_len, item_min, item_max, non_decreasing=False):
    if not present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if len(value) < min_len or len(value) > max_len:
        bad("%s must hold between %d and %d entries." % (name, min_len, max_len))
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            bad("%s entries must be integers." % name)
        if item < item_min or item > item_max:
            bad("%s entries must be between %d and %d." % (name, item_min, item_max))
        out.append(item)
    if non_decreasing:
        for index in range(1, len(out)):
            if out[index] < out[index - 1]:
                bad("%s must be non-decreasing." % name)
    return out


def unique_or_reject(collection, predicate, message):
    for row in collection.values():
        if predicate(row):
            bad(message)
