"""Payload schema validation (PRD 2.10 tier 3) and pagination parsing (PRD 2.3)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import dec, parse_ts

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def fail(message):
    raise ApiError("ERR_VALIDATION", message)


def raw_body():
    """The JSON body as a dict. A missing body is treated as an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("Request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("Request body must be a JSON object")
    return payload


def _is_int(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return float(value).is_integer()
    return False


def _check_bounds(name, number, rule):
    if "gt" in rule and not number > dec(rule["gt"]):
        fail("%s must be greater than %s" % (name, rule["gt"]))
    if "gte" in rule and not number >= dec(rule["gte"]):
        fail("%s must be greater than or equal to %s" % (name, rule["gte"]))
    if "lt" in rule and not number < dec(rule["lt"]):
        fail("%s must be less than %s" % (name, rule["lt"]))
    if "lte" in rule and not number <= dec(rule["lte"]):
        fail("%s must be less than or equal to %s" % (name, rule["lte"]))


def _coerce(name, value, rule):
    kind = rule.get("type", "string")
    if value is None:
        if rule.get("nullable"):
            return None
        fail("%s must not be null" % name)
    if kind == "string":
        if not isinstance(value, str):
            fail("%s must be a string" % name)
        if not rule.get("allow_blank") and not value.strip():
            fail("%s must not be blank" % name)
        if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
            fail("%s does not match the required format" % name)
        if "max_length" in rule and len(value) > rule["max_length"]:
            fail("%s is too long" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            fail("%s must be a string" % name)
        if value not in rule["values"]:
            fail("%s must be one of %s" % (name, ", ".join(rule["values"])))
        return value
    if kind == "enum_list":
        if not isinstance(value, list):
            fail("%s must be an array" % name)
        if not value:
            fail("%s must not be empty" % name)
        seen = set()
        for item in value:
            if not isinstance(item, str) or item not in rule["values"]:
                fail("%s must contain only %s" % (name, ", ".join(rule["values"])))
            if item in seen:
                fail("%s must not contain duplicates" % name)
            seen.add(item)
        return list(value)
    if kind == "int":
        if not _is_int(value):
            fail("%s must be an integer" % name)
        number = dec(int(value))
        _check_bounds(name, number, rule)
        return int(value)
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            fail("%s must be a number" % name)
        try:
            number = dec(value)
        except (InvalidOperation, ValueError):
            fail("%s must be a number" % name)
        if not number.is_finite():
            fail("%s must be a finite number" % name)
        _check_bounds(name, number, rule)
        return number
    if kind == "bool":
        if not isinstance(value, bool):
            fail("%s must be a boolean" % name)
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            fail("%s must be an ISO 8601 timestamp string" % name)
        parsed = parse_ts(value)
        if parsed is None:
            fail("%s must be a valid ISO 8601 timestamp" % name)
        return parsed
    if kind == "id":
        if not isinstance(value, str) or not value.strip():
            fail("%s must be a non-empty identifier string" % name)
        return value
    fail("%s has an unsupported type" % name)


def validate_payload(spec, raw=None, at_least_one=False):
    """Validate the body against `spec`, returning coerced values.

    Unknown fields, missing required fields, bad enum members, out-of-range
    numbers and malformed timestamps all raise ERR_VALIDATION.
    """
    body = raw_body() if raw is None else raw
    unknown = [key for key in body.keys() if key not in spec]
    if unknown:
        fail("Unknown field(s): %s" % ", ".join(sorted(unknown)))
    result = {}
    for name, rule in spec.items():
        if name in body:
            result[name] = _coerce(name, body[name], rule)
        elif rule.get("required"):
            fail("%s is required" % name)
        elif "default" in rule:
            result[name] = rule["default"]
    if at_least_one and not any(name in body for name in spec):
        fail("At least one updatable field must be supplied")
    result["__present__"] = set(body.keys())
    return result


def present(payload, name):
    return name in payload.get("__present__", set())


def forbid(payload, name, reason):
    if present(payload, name):
        fail("%s must not be supplied %s" % (name, reason))


def require(payload, name, reason):
    if not present(payload, name):
        fail("%s is required %s" % (name, reason))


def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        if not re.fullmatch(r"-?\d+", (raw or "").strip()):
            fail("limit must be an integer")
        limit = int(raw)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail("limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if "offset" in args:
        raw = args.get("offset")
        if not re.fullmatch(r"-?\d+", (raw or "").strip()):
            fail("offset must be an integer")
        offset = int(raw)
        if offset < OFFSET_MIN:
            fail("offset must be greater than or equal to %d" % OFFSET_MIN)
    return limit, offset
