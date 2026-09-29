"""Schema-rung helpers (PRD 2.6 rungs 4-8) plus filter parsing."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_ts

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        bad("request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("request body must be a JSON object")
    return data


def present(data, name):
    return name in data and data[name] is not None


def get_str(data, name, required=True, min_len=1, max_len=None, default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if len(value) < min_len:
        bad("%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long" % name)
    return value


def get_enum(data, name, allowed, required=True, default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def get_int(data, name, required=True, minimum=None, maximum=None, default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s is below the accepted minimum" % name)
    if maximum is not None and value > maximum:
        bad("%s is above the accepted maximum" % name)
    return value


def get_dec(data, name, required=True, minimum=None, maximum=None,
            scale=None, gt=None, default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % name)
    try:
        dec = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % name)
    if dec != dec:  # NaN guard
        bad("%s must be a number" % name)
    if scale is not None and -dec.as_tuple().exponent > scale:
        bad("%s carries more than %d decimal places" % (name, scale))
    if gt is not None and dec <= Decimal(str(gt)):
        bad("%s must be greater than %s" % (name, gt))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("%s is below the accepted minimum" % name)
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("%s is above the accepted maximum" % name)
    return dec


def get_bool(data, name, required=True, default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def get_ts(data, name, required=True, default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    parsed = parse_ts(value)
    if parsed is None:
        bad("%s must be an RFC 3339 timestamp with a trailing Z" % name)
    return parsed


def get_code_list(data, name, allowed=None, required=True, non_empty=True,
                  default=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    for item in value:
        if not isinstance(item, str) or item == "":
            bad("%s must contain non-empty strings" % name)
        if allowed is not None and item not in allowed:
            bad("%s contains an unsupported value" % name)
    if non_empty and not value:
        bad("%s must not be empty" % name)
    return list(value)


def get_id(data, name, required=True):
    """Body foreign keys are strings; a non-string is a schema violation."""
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None
    value = data[name]
    if not isinstance(value, str) or value == "":
        bad("%s must be a resource id" % name)
    return value


# --------------------------------------------------------------- lookups -----

def fetch(table, ident, error_id):
    if ident is None:
        return None
    rec = table.get(ident)
    if rec is None:
        raise ApiError(error_id, "%s does not exist" % ident)
    return rec


def unique_code(table, field, value):
    for rec in table.values():
        if rec.get(field) == value:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "%s %s already exists" % (field, value))


# --------------------------------------------------------------- filters -----

def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_enum(name, allowed):
    raw = filter_value(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return raw


def filter_bool(name):
    raw = filter_value(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s must be a boolean" % name)


def apply_filters(rows, specs):
    """specs: iterable of (row_field, wanted_value) pairs."""
    out = rows
    for field, wanted in specs:
        if wanted is None:
            continue
        out = [r for r in out if r.get(field) == wanted]
    return out
