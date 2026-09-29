"""Rank 8 request-shape validation: ERR_INVALID_REQUEST (400).

Covers presence of every non-optional field, enum membership, integer and
numeric ranges, duplicate-free arrays, and outright rejection of unknown
fields.
"""
from flask import request

from db import parse_date, parse_datetime
from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def read_body():
    """Body must be a JSON object (absent body is treated as an empty one)."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_scalar(name, value, rule):
    kind = rule["type"]
    if kind == "string":
        if not isinstance(value, str):
            bad("%s must be a string." % name)
        if len(value) < rule.get("min_len", 1):
            bad("%s must not be empty." % name)
        if "max_len" in rule and len(value) > rule["max_len"]:
            bad("%s exceeds its maximum length." % name)
        return value
    if kind == "text":
        if not isinstance(value, str):
            bad("%s must be a string." % name)
        if "max_len" in rule and len(value) > rule["max_len"]:
            bad("%s exceeds its maximum length." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in rule["values"]:
            bad("%s must be one of %s." % (name, ", ".join(rule["values"])))
        return value
    if kind == "int":
        if not _is_int(value):
            bad("%s must be an integer." % name)
        if "min" in rule and value < rule["min"]:
            bad("%s is below its minimum." % name)
        if "max" in rule and value > rule["max"]:
            bad("%s is above its maximum." % name)
        return value
    if kind == "number":
        if not _is_number(value):
            bad("%s must be a number." % name)
        if "min" in rule and value < rule["min"]:
            bad("%s is below its minimum." % name)
        if "max" in rule and value > rule["max"]:
            bad("%s is above its maximum." % name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad("%s must be a boolean." % name)
        return value
    if kind == "id":
        if not isinstance(value, str) or not value:
            bad("%s must be a non-empty string identifier." % name)
        return value
    if kind == "date":
        parsed = parse_date(value)
        if parsed is None:
            bad("%s must be an ISO 8601 calendar date." % name)
        return parsed
    if kind == "datetime":
        parsed = parse_datetime(value)
        if parsed is None:
            bad("%s must be an ISO 8601 UTC instant." % name)
        return parsed
    if kind == "enum_array":
        if not isinstance(value, list):
            bad("%s must be an array." % name)
        seen = []
        for item in value:
            if not isinstance(item, str) or item not in rule["values"]:
                bad("%s contains an unsupported value." % name)
            if item in seen:
                bad("%s must not contain duplicates." % name)
            seen.append(item)
        if rule.get("non_empty") and not seen:
            bad("%s must not be empty." % name)
        return seen
    if kind == "string_array":
        if not isinstance(value, list):
            bad("%s must be an array." % name)
        seen = []
        for item in value:
            if not isinstance(item, str) or not item:
                bad("%s must contain non-empty strings." % name)
            if item in seen:
                bad("%s must not contain duplicates." % name)
            seen.append(item)
        if rule.get("non_empty") and not seen:
            bad("%s must not be empty." % name)
        return seen
    if kind == "int_map":
        if not isinstance(value, dict):
            bad("%s must be an object." % name)
        return value
    bad("%s could not be validated." % name)


def validate(body, spec):
    """Validate `body` against `spec`; return coerced values by field name."""
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    for key in body.keys():
        if key not in spec:
            bad("Unknown field: %s" % key)
    out = {}
    for name, rule in spec.items():
        present = name in body and body[name] is not None
        if not present:
            if rule.get("required"):
                bad("Missing required field: %s" % name)
            out[name] = None
            continue
        out[name] = _check_scalar(name, body[name], rule)
    return out


def present(body, name):
    return name in body and body[name] is not None
