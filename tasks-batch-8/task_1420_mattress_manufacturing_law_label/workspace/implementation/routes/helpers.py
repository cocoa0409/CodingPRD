"""Shared request-parsing helpers enforcing PRD section 2.8 tier 4."""
from flask import request

import errors

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "request body must be a JSON object")
    return data


def require(data, field):
    val = data.get(field, _MISSING)
    if val is _MISSING or val is None:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "missing required field: %s" % field)
    return val


def optional(data, field, default=None):
    val = data.get(field, _MISSING)
    if val is _MISSING:
        return default
    return val


def _is_bool(v):
    return isinstance(v, bool)


def as_string(v, field):
    if not isinstance(v, str) or v == "":
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "field %s must be a non-empty string" % field)
    return v


def as_bool(v, field):
    if not _is_bool(v):
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "field %s must be a boolean" % field)
    return v


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "field %s must be an integer" % field)
    return v


def as_number(v, field):
    """Accepts int/float (not bool); returns the value for Decimal conversion."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "field %s must be a number" % field)
    return v


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "field %s must be one of %s" % (field, sorted(allowed)))
    return v


def as_string_list(v, field):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "field %s must be a list of strings" % field)
    return v


def check_occ(expected, current):
    """Tier 12 optimistic concurrency: mandatory expected-version field."""
    exp = as_int(expected, "expected version")
    if exp != current:
        errors.raise_err(errors.ERR_STALE_VERSION, "stale version")
