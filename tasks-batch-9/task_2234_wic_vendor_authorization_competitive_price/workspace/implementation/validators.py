"""Request-shape validation (ladder rule 7 -> ERR_INVALID_REQUEST) and pagination."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from config import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT
from errors import ApiError

MISSING = object()

CLAIM_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
UPC_RE = re.compile(r"^[0-9]{8,14}$")


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object.")
    return data


def present(payload, name):
    return name in payload and payload[name] is not None


def req_string(payload, name, min_len=1, max_len=None):
    value = payload.get(name)
    if not isinstance(value, str) or len(value) < min_len:
        raise invalid("Field '%s' must be a non-empty string." % name)
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_string(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload.get(name)
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    return value


def req_enum(payload, name, allowed):
    value = payload.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % name)
    return value


def req_int(payload, name, minimum=0, maximum=None):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    value = _as_int(payload[name], name)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be at most %s." % (name, maximum))
    return value


def opt_int(payload, name, default=None, minimum=0, maximum=None, nullable=False):
    if name not in payload:
        return default
    if payload[name] is None:
        if nullable:
            return None
        return default
    return req_int(payload, name, minimum=minimum, maximum=maximum)


def req_number(payload, name, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise invalid("Field '%s' must be a number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise invalid("Field '%s' must be at most %s." % (name, maximum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        raise invalid("Field '%s' must be greater than %s." % (name, exclusive_min))
    if exclusive_max is not None and dec >= Decimal(str(exclusive_max)):
        raise invalid("Field '%s' must be less than %s." % (name, exclusive_max))
    return value


def opt_number(payload, name, default=None, **kwargs):
    if not present(payload, name):
        return default
    return req_number(payload, name, **kwargs)


def req_bool(payload, name):
    value = payload.get(name)
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if not present(payload, name):
        return default
    return req_bool(payload, name)


def req_instant(payload, name):
    if name not in payload or payload[name] is None:
        raise invalid("Field '%s' is required." % name)
    parsed = clock.parse_instant(payload[name])
    if parsed is None:
        raise invalid("Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def req_claim_month(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not CLAIM_MONTH_RE.match(value):
        raise invalid("Field '%s' must match YYYY-MM." % name)
    return value


def req_upc(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not UPC_RE.match(value):
        raise invalid("Field '%s' must be 8 to 14 digits." % name)
    return value


def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' must not be negative.")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]
