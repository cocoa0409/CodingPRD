"""Request-shape validation (ladder level 5 -> ERR_INVALID_REQUEST)."""

import re

import db
from errors import ApiError

_UPPER_CODE = re.compile(r"^[A-Z0-9-]+$")
_DIGITS = re.compile(r"^[0-9]+$")


def fail(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def check_unknown(payload, spec, extra_allowed=()):
    allowed = set(spec.keys()) | set(extra_allowed)
    for key in payload.keys():
        if key not in allowed:
            fail("Unknown field '%s'" % key)


def parse(payload, spec, extra_allowed=(), skip=()):
    """Validate `payload` against `spec`; returns resolved values."""
    check_unknown(payload, spec, extra_allowed)
    out = {}
    for name, rule in spec.items():
        if name in skip:
            continue
        present = name in payload
        value = payload.get(name)
        if not present or value is None:
            if rule.get("required"):
                fail("Field '%s' is required" % name)
            out[name] = rule.get("default")
            continue
        out[name] = _one(name, value, rule)
    return out


def _one(name, value, rule):
    kind = rule.get("type", "string")
    if kind == "string":
        return _string(name, value, rule)
    if kind == "integer":
        return _integer(name, value, rule)
    if kind == "boolean":
        if not isinstance(value, bool):
            fail("Field '%s' must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            fail("Field '%s' must be a string" % name)
        if value not in rule["values"]:
            fail("Field '%s' must be one of %s" % (name, ", ".join(rule["values"])))
        return value
    if kind == "date":
        if not isinstance(value, str):
            fail("Field '%s' must be an ISO date string" % name)
        parsed = db.parse_date(value)
        if parsed is None:
            fail("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % name)
        return value
    if kind == "instant":
        if not isinstance(value, str):
            fail("Field '%s' must be an ISO 8601 timestamp" % name)
        parsed = db.parse_instant(value)
        if parsed is None:
            fail("Field '%s' must be an ISO 8601 UTC timestamp" % name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            fail("Field '%s' must be an array" % name)
        if "max_items" in rule and len(value) > rule["max_items"]:
            fail("Field '%s' may hold at most %d entries" % (name, rule["max_items"]))
        if "min_items" in rule and len(value) < rule["min_items"]:
            fail("Field '%s' must hold at least %d entries" % (name, rule["min_items"]))
        item_rule = rule.get("items")
        if item_rule is not None:
            return [_one(name, entry, item_rule) for entry in value]
        return value
    if kind == "object":
        if not isinstance(value, dict):
            fail("Field '%s' must be an object" % name)
        return value
    return value


def _string(name, value, rule):
    if not isinstance(value, str):
        fail("Field '%s' must be a string" % name)
    if rule.get("non_blank", True) and value.strip() == "":
        fail("Field '%s' must not be blank" % name)
    if "exact_len" in rule and len(value) != rule["exact_len"]:
        fail("Field '%s' must be exactly %d characters" % (name, rule["exact_len"]))
    if "min_len" in rule and len(value) < rule["min_len"]:
        fail("Field '%s' must be at least %d characters" % (name, rule["min_len"]))
    if "max_len" in rule and len(value) > rule["max_len"]:
        fail("Field '%s' must be at most %d characters" % (name, rule["max_len"]))
    if rule.get("digits") and not _DIGITS.match(value):
        fail("Field '%s' must contain digits only" % name)
    if rule.get("offer_code") and not _UPPER_CODE.match(value):
        fail("Field '%s' must be uppercase alphanumerics and hyphens" % name)
    return value


def _integer(name, value, rule):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Field '%s' must be an integer" % name)
    if "min" in rule and value < rule["min"]:
        fail("Field '%s' must be at least %d" % (name, rule["min"]))
    if "max" in rule and value > rule["max"]:
        fail("Field '%s' must be at most %d" % (name, rule["max"]))
    return value


def require_no_body(payload):
    if payload:
        fail("This endpoint accepts no request body fields")
