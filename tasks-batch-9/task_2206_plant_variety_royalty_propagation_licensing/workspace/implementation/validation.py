"""Request body / query validation (PRD 2.8 rung 3)."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_dt, rh

BAD = "ERR_INVALID_REQUEST"

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _bad(detail):
    raise ApiError(BAD, detail)


# ---------------------------------------------------------------- specs


def Str(min_len=1, max_len=None, pattern=None):
    return {"kind": "str", "min_len": min_len, "max_len": max_len, "pattern": pattern}


def Enum(values):
    return {"kind": "enum", "values": list(values)}


def Int(minimum=None, maximum=None):
    return {"kind": "int", "min": minimum, "max": maximum}


def Dec(max_dp, minimum=None, maximum=None):
    return {"kind": "dec", "max_dp": max_dp, "min": minimum, "max": maximum}


def DateTime():
    return {"kind": "datetime"}


def Bool():
    return {"kind": "bool"}


def StrList(item, non_empty=True, unique=True):
    return {"kind": "list", "item": item, "non_empty": non_empty, "unique": unique}


# Reusable code shapes.
UPPER_2_4 = Str(2, 4, r"^[A-Z0-9]{2,4}$")
UPPER_2_6 = Str(2, 6, r"^[A-Z0-9]{2,6}$")
UPPER_2_12 = Str(2, 12, r"^[A-Z0-9]{2,12}$")
TERRITORY = Str(2, 8, r"^[A-Z0-9-]{2,8}$")
ID = Str(1, 200)


# ---------------------------------------------------------------- coercion


def _check_str(name, value, spec):
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % name)
    if spec["min_len"] is not None and len(value) < spec["min_len"]:
        _bad("Field '%s' is shorter than %d characters." % (name, spec["min_len"]))
    if spec["max_len"] is not None and len(value) > spec["max_len"]:
        _bad("Field '%s' is longer than %d characters." % (name, spec["max_len"]))
    if spec["pattern"] is not None and not re.match(spec["pattern"], value):
        _bad("Field '%s' does not match the required format." % name)
    return value


def _check_int(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % name)
    if spec["min"] is not None and value < spec["min"]:
        _bad("Field '%s' must be at least %s." % (name, spec["min"]))
    if spec["max"] is not None and value > spec["max"]:
        _bad("Field '%s' must be at most %s." % (name, spec["max"]))
    return value


def _check_dec(name, value, spec):
    if isinstance(value, bool):
        _bad("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        parsed = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            _bad("Field '%s' must be a number." % name)
    else:
        _bad("Field '%s' must be a number." % name)
    if not parsed.is_finite():
        _bad("Field '%s' must be a finite number." % name)
    exponent = parsed.as_tuple().exponent
    dp = -exponent if exponent < 0 else 0
    if dp > spec["max_dp"]:
        _bad("Field '%s' carries more than %d decimal places." % (name, spec["max_dp"]))
    if spec["min"] is not None and parsed < Decimal(str(spec["min"])):
        _bad("Field '%s' must be at least %s." % (name, spec["min"]))
    if spec["max"] is not None and parsed > Decimal(str(spec["max"])):
        _bad("Field '%s' must be at most %s." % (name, spec["max"]))
    return rh(parsed, spec["max_dp"])


def _check_value(name, value, spec):
    kind = spec["kind"]
    if kind == "str":
        return _check_str(name, value, spec)
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            _bad("Field '%s' must be one of %s." % (name, ", ".join(spec["values"])))
        return value
    if kind == "int":
        return _check_int(name, value, spec)
    if kind == "dec":
        return _check_dec(name, value, spec)
    if kind == "bool":
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            _bad("Field '%s' must be an ISO 8601 timestamp string." % name)
        if parse_dt(value) is None:
            _bad("Field '%s' is not a valid ISO 8601 timestamp." % name)
        return value
    if kind == "list":
        if not isinstance(value, list):
            _bad("Field '%s' must be an array." % name)
        if spec["non_empty"] and len(value) == 0:
            _bad("Field '%s' must not be empty." % name)
        out = []
        for entry in value:
            out.append(_check_value(name, entry, spec["item"]))
        if spec["unique"] and len(set(out)) != len(out):
            _bad("Field '%s' must not contain duplicates." % name)
        return out
    _bad("Field '%s' is not understood." % name)


# ---------------------------------------------------------------- body


def raw_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        _bad("The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        _bad("The request body must be a JSON object.")
    return payload


def validate_body(schema):
    """`schema` is an ordered sequence of (name, spec, required) tuples."""
    payload = raw_body()
    allowed = set(name for name, _spec, _req in schema)
    for key in payload.keys():
        if key not in allowed:
            _bad("Unknown field '%s'." % key)
    result = {}
    for name, spec, required in schema:
        if name not in payload or payload[name] is None:
            if required:
                _bad("Field '%s' is required." % name)
            result[name] = None
            continue
        result[name] = _check_value(name, payload[name], spec)
    return result


# ---------------------------------------------------------------- query


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            _bad("Query parameter 'limit' must be between %d and %d."
                 % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            _bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def filters(*names):
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def bool_filter(value):
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    _bad("Boolean query parameter must be 'true' or 'false'.")
