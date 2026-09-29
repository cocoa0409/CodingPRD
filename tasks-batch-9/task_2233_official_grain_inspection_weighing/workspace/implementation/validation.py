"""Body schema validation — ladder rung 5, ERR_INVALID_REQUEST (422)."""

import re

from flask import request

from errors import ApiError
from store import parse_dt


def _invalid(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def raw_body():
    """Read the JSON body.  A missing body is an empty object."""
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        _invalid("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        _invalid("Request body must be a JSON object")
    return parsed


def parse(spec):
    """Validate the request body against `spec` and return normalised values."""
    return parse_present(spec)[0]


def parse_present(spec):
    """Like parse(), but also returns the set of keys the caller supplied."""
    body = raw_body()
    for key in body:
        if key not in spec:
            _invalid("Unknown field '%s'" % key)
    out = {}
    for name, desc in spec.items():
        present = name in body
        value = body.get(name)
        if not present or value is None:
            if value is None and present and desc.get("nullable"):
                out[name] = None
                continue
            if desc.get("required"):
                _invalid("Field '%s' is required" % name)
            out[name] = desc.get("default")
            continue
        out[name] = _coerce(name, value, desc)
    return out, set(body.keys())


def _coerce(name, value, desc):
    kind = desc.get("type", "string")
    if kind == "string":
        if not isinstance(value, str):
            _invalid("Field '%s' must be a string" % name)
        if len(value) < desc.get("minlen", 1 if desc.get("required") else 0):
            _invalid("Field '%s' is too short" % name)
        if "maxlen" in desc and len(value) > desc["maxlen"]:
            _invalid("Field '%s' is too long" % name)
        if "pattern" in desc and not re.fullmatch(desc["pattern"], value):
            _invalid("Field '%s' does not match the required pattern" % name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _invalid("Field '%s' must be an integer" % name)
        _range(name, value, desc)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _invalid("Field '%s' must be a number" % name)
        _range(name, value, desc)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            _invalid("Field '%s' must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in desc["values"]:
            _invalid("Field '%s' must be one of %s" % (name, sorted(desc["values"])))
        return value
    if kind == "datetime":
        parsed = parse_dt(value)
        if parsed is None:
            _invalid("Field '%s' must be an ISO 8601 instant" % name)
        return parsed
    if kind == "enum_array":
        if not isinstance(value, list):
            _invalid("Field '%s' must be an array" % name)
        if len(value) < desc.get("min_items", 1):
            _invalid("Field '%s' must not be empty" % name)
        if "max_items" in desc and len(value) > desc["max_items"]:
            _invalid("Field '%s' has too many items" % name)
        for item in value:
            if not isinstance(item, str) or item not in desc["values"]:
                _invalid("Field '%s' contains an unsupported value" % name)
        return list(value)
    if kind == "drafts":
        return _drafts(name, value, desc)
    _invalid("Field '%s' could not be validated" % name)


def _range(name, value, desc):
    if "min" in desc and value < desc["min"]:
        _invalid("Field '%s' is below the permitted minimum" % name)
    if "max" in desc and value > desc["max"]:
        _invalid("Field '%s' is above the permitted maximum" % name)
    if desc.get("exclusive_min") is not None and value <= desc["exclusive_min"]:
        _invalid("Field '%s' must be greater than %s" % (name, desc["exclusive_min"]))


def _drafts(name, value, desc):
    if not isinstance(value, list):
        _invalid("Field '%s' must be an array" % name)
    if len(value) < desc.get("min_items", 1) or len(value) > desc.get("max_items", 20):
        _invalid("Field '%s' must hold between 1 and 20 drafts" % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            _invalid("Each draft must be an object")
        for key in item:
            if key not in ("gross_lbs", "tare_lbs"):
                _invalid("Unknown draft field '%s'" % key)
        for key in ("gross_lbs", "tare_lbs"):
            if key not in item or item[key] is None:
                _invalid("Draft field '%s' is required" % key)
            if isinstance(item[key], bool) or not isinstance(item[key], int):
                _invalid("Draft field '%s' must be an integer" % key)
        if item["tare_lbs"] < 0:
            _invalid("Draft field 'tare_lbs' must be at least 0")
        out.append({"gross_lbs": item["gross_lbs"], "tare_lbs": item["tare_lbs"]})
    return out
