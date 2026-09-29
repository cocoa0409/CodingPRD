"""Request-shape validation (PRD 2.8 rank 4 -> ERR_INVALID_REQUEST)."""
import json
from decimal import Decimal, InvalidOperation

from flask import request

from clock import format_instant, parse_instant
from errors import api_error

MISSING = object()


def F(name, kind, required=True, default=MISSING, nullable=False, enum=None,
      gt=None, ge=None, lt=None, le=None, min_len=None, max_len=None):
    return {
        "name": name, "kind": kind, "required": required, "default": default,
        "nullable": nullable, "enum": enum, "gt": gt, "ge": ge, "lt": lt,
        "le": le, "min_len": min_len, "max_len": max_len,
    }


def bad(msg):
    return api_error("ERR_INVALID_REQUEST", msg)


def read_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def _to_decimal(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad("Field '%s' must be a number." % name)


def _check_bounds(spec, dec, name):
    for key, op, text in (
        ("gt", "gt", "greater than"),
        ("ge", "ge", "at least"),
        ("lt", "lt", "less than"),
        ("le", "le", "at most"),
    ):
        bound = spec.get(key)
        if bound is None:
            continue
        b = Decimal(str(bound))
        if op == "gt" and not dec > b:
            raise bad("Field '%s' must be %s %s." % (name, text, bound))
        if op == "ge" and not dec >= b:
            raise bad("Field '%s' must be %s %s." % (name, text, bound))
        if op == "lt" and not dec < b:
            raise bad("Field '%s' must be %s %s." % (name, text, bound))
        if op == "le" and not dec <= b:
            raise bad("Field '%s' must be %s %s." % (name, text, bound))


def _coerce(spec, value):
    name = spec["name"]
    kind = spec["kind"]
    if kind == "str":
        if not isinstance(value, str):
            raise bad("Field '%s' must be a string." % name)
        if spec["min_len"] is not None and len(value) < spec["min_len"]:
            raise bad("Field '%s' is too short." % name)
        if spec["max_len"] is not None and len(value) > spec["max_len"]:
            raise bad("Field '%s' is too long." % name)
        if spec["enum"] is not None and value not in spec["enum"]:
            raise bad("Field '%s' must be one of %s." % (name, ", ".join(spec["enum"])))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad("Field '%s' must be an integer." % name)
        _check_bounds(spec, Decimal(value), name)
        return value
    if kind == "num":
        dec = _to_decimal(value, name)
        _check_bounds(spec, dec, name)
        return dec
    if kind == "iso":
        if not isinstance(value, str):
            raise bad("Field '%s' must be an ISO 8601 string." % name)
        try:
            parsed = parse_instant(value)
        except Exception:
            raise bad("Field '%s' must be an ISO 8601 UTC instant." % name)
        return format_instant(parsed)
    raise bad("Field '%s' has an unsupported type." % name)


def validate_body(raw, specs):
    """Validate a parsed JSON body against an ordered list of field specs."""
    known = set(s["name"] for s in specs)
    for key in raw.keys():
        if key not in known:
            raise bad("Unknown field '%s'." % key)
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in raw:
            if spec["required"]:
                raise bad("Field '%s' is required." % name)
            out[name] = None if spec["default"] is MISSING else spec["default"]
            continue
        value = raw[name]
        if value is None:
            if spec["nullable"]:
                out[name] = None
                continue
            raise bad("Field '%s' must not be null." % name)
        out[name] = _coerce(spec, value)
    return out


def body(specs):
    return validate_body(read_body(), specs)


def no_body():
    """Endpoints declaring an empty input accept only an absent or empty body."""
    raw = read_body()
    if raw:
        raise bad("This endpoint accepts no request body fields.")
    return {}
