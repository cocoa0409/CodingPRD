"""Request-shape validation (PRD 2.9 step 5).  Every failure is ERR_INVALID_REQUEST."""
from flask import request

from errors import fail
from util import parse_date

MISSING = object()


def raw_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _check_int(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if "min" in spec and value < spec["min"]:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, spec["min"]))
    if "max" in spec and value > spec["max"]:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, spec["max"]))
    return value


def _check_str(name, value, spec):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if not spec.get("allow_empty") and value == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty" % name)
    if "enum" in spec and value not in spec["enum"]:
        fail("ERR_INVALID_REQUEST", "%s has an unknown value" % name)
    if "min_len" in spec and len(value) < spec["min_len"]:
        fail("ERR_INVALID_REQUEST", "%s is too short" % name)
    if "max_len" in spec and len(value) > spec["max_len"]:
        fail("ERR_INVALID_REQUEST", "%s is too long" % name)
    return value


def check_field(name, value, spec):
    kind = spec.get("type", "str")
    if value is None:
        if spec.get("nullable"):
            return None
        fail("ERR_INVALID_REQUEST", "%s must not be null" % name)
    if kind == "int":
        return _check_int(name, value, spec)
    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
        return value
    if kind == "date":
        if parse_date(value) is None:
            fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 calendar date" % name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
        if spec.get("min_items") and len(value) < spec["min_items"]:
            fail("ERR_INVALID_REQUEST", "%s must not be empty" % name)
        return value
    if kind == "object":
        if not isinstance(value, dict):
            fail("ERR_INVALID_REQUEST", "%s must be an object" % name)
        return value
    return _check_str(name, value, spec)


def parse_body(spec):
    """spec: {field: {type, required, enum, min, max, nullable, default}}"""
    body = raw_body()
    out = {}
    for name, field_spec in spec.items():
        present = name in body
        value = body.get(name, MISSING)
        if not present or value is MISSING:
            if field_spec.get("required"):
                fail("ERR_INVALID_REQUEST", "%s is required" % name)
            out[name] = field_spec.get("default")
            continue
        out[name] = check_field(name, value, field_spec)
    out["__raw__"] = body
    return out


def present(parsed, name):
    return name in parsed.get("__raw__", {})
