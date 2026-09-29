"""Request-schema validation helpers (PRD 2.8 step 5) and lookup helpers."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from db import db, parse_dt, sort_rows
from errors import fail

_STATE_CODE = re.compile(r"^[A-Z]{2}$")

_SENTINEL = object()


def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------- scalars


def opt_str(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return value


def req_str(data, key):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return value


def req_state_code(data, key):
    value = req_str(data, key)
    if not _STATE_CODE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be exactly two uppercase letters." % key)
    return value


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, allowed)


def _decimal(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)


def req_num(data, key, minimum=None, maximum=None, exclusive_min=None, max_decimals=None):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    return _check_num(key, _decimal(key, data[key]), minimum, maximum, exclusive_min, max_decimals)


def opt_num(data, key, default=None, minimum=None, maximum=None, exclusive_min=None,
            max_decimals=None):
    if key not in data or data[key] is None:
        return default
    return _check_num(key, _decimal(key, data[key]), minimum, maximum, exclusive_min, max_decimals)


def _check_num(key, value, minimum, maximum, exclusive_min, max_decimals):
    if minimum is not None and value < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (key, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (key, maximum))
    if exclusive_min is not None and value <= Decimal(str(exclusive_min)):
        fail("ERR_INVALID_REQUEST", "%s must be greater than %s." % (key, exclusive_min))
    if max_decimals is not None and -value.as_tuple().exponent > max_decimals:
        fail("ERR_INVALID_REQUEST",
             "%s must have at most %d decimal places." % (key, max_decimals))
    return value


def _integer(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = _integer(key, data[key])
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (key, maximum))
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        return default
    return req_int(data, key, minimum, maximum)


def req_bool(data, key):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    if not isinstance(data[key], bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return data[key]


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_bool(data, key)


def req_dt(data, key):
    value = req_str(data, key)
    try:
        return parse_dt(value)
    except Exception:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % key)


def opt_dt(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_dt(data, key)


def opt_str_list(data, key, default=None):
    if key not in data or data[key] is None:
        return list(default) if default is not None else None
    value = data[key]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        fail("ERR_INVALID_REQUEST", "%s must be an array of strings." % key)
    return list(value)


# ------------------------------------------------------------- pagination


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def query_filters(rows, spec):
    """spec maps query-parameter name -> (field name, coercion)."""
    out = list(rows)
    for param, (field, coerce) in spec.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        value = coerce(raw) if coerce else raw
        out = [r for r in out if r.get(field) == value]
    return out


def as_bool(raw):
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def as_int(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def paginate(rows, limit, offset):
    ordered = sort_rows(rows)
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ------------------------------------------------------------ lookups

_COLLECTIONS = {
    "community": ("communities", "ERR_COMMUNITY_NOT_FOUND"),
    "firm_panel": ("firm_panels", "ERR_FIRM_PANEL_NOT_FOUND"),
    "property": ("properties", "ERR_PROPERTY_NOT_FOUND"),
    "structure": ("structures", "ERR_STRUCTURE_NOT_FOUND"),
    "permit": ("permits", "ERR_PERMIT_NOT_FOUND"),
    "certificate": ("certificates", "ERR_CERTIFICATE_NOT_FOUND"),
    "record": ("records", "ERR_IMPROVEMENT_RECORD_NOT_FOUND"),
    "case": ("cases", "ERR_DETERMINATION_CASE_NOT_FOUND"),
    "inspection": ("inspections", "ERR_INSPECTION_NOT_FOUND"),
    "violation": ("violations", "ERR_VIOLATION_NOT_FOUND"),
    "order": ("orders", "ERR_ORDER_NOT_FOUND"),
    "loss_area": ("loss_areas", "ERR_LOSS_AREA_NOT_FOUND"),
    "standard": ("standards", "ERR_HIGHER_STANDARD_NOT_FOUND"),
    "cycle": ("cycles", "ERR_CRS_CYCLE_NOT_FOUND"),
}


def lookup(kind, identifier):
    collection, error_id = _COLLECTIONS[kind]
    row = getattr(db, collection).get(identifier)
    if row is None:
        fail(error_id)
    return row


def find(kind, identifier):
    collection, _ = _COLLECTIONS[kind]
    return getattr(db, collection).get(identifier)


def fk(data, key, kind, required=True):
    """Body foreign key: schema check then existence check."""
    if key not in data or data[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % key)
        return None
    identifier = data[key]
    if not isinstance(identifier, str) or not identifier.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return identifier
