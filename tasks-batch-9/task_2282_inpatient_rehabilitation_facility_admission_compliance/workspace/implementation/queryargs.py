"""Query-string filter helpers (validated at ladder rank 5)."""

from flask import request

from errors import ApiError
from util import parse_date


def str_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def enum_arg(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def int_arg(name, minimum=None, maximum=None):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and parsed < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % name)
    if maximum is not None and parsed > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % name)
    return parsed


def date_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    parse_date(value, name)
    return value


def matches(entity, filters):
    for field, expected in filters.items():
        if expected is None:
            continue
        if entity.get(field) != expected:
            return False
    return True
