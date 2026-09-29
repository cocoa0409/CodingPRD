"""Request-shape validation (PRD section 2.8 rule 5 -> ERR_INVALID_REQUEST).

`check_body` is deliberately strict: every required field must be present and
non-null, enums must carry a declared member, integers must be integers,
monetary and subscriber fields must not be negative, period months and
territory codes must match their patterns, and NO unknown field may be present.
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import D, PERIOD_RE, TERRITORY_RE, parse_iso


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def raw_body():
    """Return the parsed JSON body, or {} for an absent body."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        bad("request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad("request body must be a JSON object")
    return body


def field(kind, required=False, default=None, enum=None, minimum=None,
          maximum=None, min_len=None, max_len=None, exclusive_min=None):
    return {
        "kind": kind,
        "required": required,
        "default": default,
        "enum": enum,
        "minimum": minimum,
        "maximum": maximum,
        "min_len": min_len,
        "max_len": max_len,
        "exclusive_min": exclusive_min,
    }


def _coerce(name, spec, value):
    kind = spec["kind"]

    if kind == "string":
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if spec["min_len"] is not None and len(value) < spec["min_len"]:
            bad("%s is too short" % name)
        if spec["max_len"] is not None and len(value) > spec["max_len"]:
            bad("%s is too long" % name)
        return value

    if kind == "enum":
        if not isinstance(value, str):
            bad("%s must be a string" % name)
        if value not in (spec["enum"] or []):
            bad("%s is not a declared member" % name)
        return value

    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("%s must be an integer" % name)
        return _range(name, spec, value)

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad("%s must be a number" % name)
        try:
            dec = D(value)
        except (InvalidOperation, ValueError):
            bad("%s must be a number" % name)
        return _range(name, spec, dec)

    if kind == "bool":
        if not isinstance(value, bool):
            bad("%s must be a boolean" % name)
        return value

    if kind == "datetime":
        if not isinstance(value, str):
            bad("%s must be an ISO 8601 string" % name)
        parsed = parse_iso(value)
        if parsed is None:
            bad("%s is not a valid ISO 8601 instant" % name)
        return parsed

    if kind == "period":
        if not isinstance(value, str) or not PERIOD_RE.match(value):
            bad("%s must match YYYY-MM" % name)
        return value

    if kind == "territory":
        if not isinstance(value, str) or not TERRITORY_RE.match(value):
            bad("%s must be exactly two uppercase letters" % name)
        return value

    if kind == "id":
        if not isinstance(value, str) or not value:
            bad("%s must be a string identifier" % name)
        return value

    bad("unsupported field kind for %s" % name)


def _range(name, spec, value):
    if spec["minimum"] is not None and value < D(spec["minimum"]):
        bad("%s must be at least %s" % (name, spec["minimum"]))
    if spec["exclusive_min"] is not None and value <= D(spec["exclusive_min"]):
        bad("%s must be greater than %s" % (name, spec["exclusive_min"]))
    if spec["maximum"] is not None and value > D(spec["maximum"]):
        bad("%s must be at most %s" % (name, spec["maximum"]))
    return value


def check_body(spec, body=None):
    """Validate the JSON body against `spec`; returns a normalised dict."""
    if body is None:
        body = raw_body()
    for key in body.keys():
        if key not in spec:
            bad("unknown field %s" % key)
    out = {}
    for name, fspec in spec.items():
        present = name in body and body[name] is not None
        if not present:
            if fspec["required"]:
                bad("%s is required" % name)
            out[name] = fspec["default"]
            continue
        out[name] = _coerce(name, fspec, body[name])
    return out


def peek(field_name):
    """Best-effort read of one body field before full shape validation.

    Used by the segregation-of-duties gate (PRD 2.8 rule 3), which is evaluated
    before request shape (rule 5).
    """
    try:
        body = raw_body()
    except ApiError:
        return None
    value = body.get(field_name)
    return value


def dec_or_none(value):
    if value is None:
        return None
    return D(value)


def as_int(value):
    if isinstance(value, Decimal):
        return int(value)
    return value
