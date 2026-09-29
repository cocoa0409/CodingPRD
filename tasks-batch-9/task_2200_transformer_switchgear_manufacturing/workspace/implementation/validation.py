"""Payload-shape validation (ladder rungs 27-31) and the OCC rungs 32-33.

The ladder is banded: EVERY required-field check across the whole payload fires
before ANY type check, every type check before any enum check, and every enum
check before any range check. `validate` therefore runs four ordered passes over
the field spec rather than validating field-by-field.
"""
from flask import request

import clock
from errors import ApiError

STRING = "string"
INTEGER = "integer"
NUMBER = "number"
BOOLEAN = "boolean"
DATETIME = "datetime"
ARRAY = "array"
OBJECT = "object"


def f(name, ftype=STRING, required=False, enum=None, minimum=None, maximum=None,
      default=None, nullable=False):
    return {
        "name": name,
        "type": ftype,
        "required": required,
        "enum": enum,
        "min": minimum,
        "max": maximum,
        "default": default,
        "nullable": nullable,
    }


def body():
    """Parse the JSON body leniently: a missing or empty body is an empty dict."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_FIELD_TYPE_INVALID", "request body must be a JSON object")
    return data


def _present(payload, name):
    return name in payload and payload[name] is not None


def _type_ok(value, ftype):
    if ftype == STRING:
        return isinstance(value, str)
    if ftype == INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == BOOLEAN:
        return isinstance(value, bool)
    if ftype == DATETIME:
        return isinstance(value, str) and clock.parse(value) is not None
    if ftype == ARRAY:
        return isinstance(value, list)
    if ftype == OBJECT:
        return isinstance(value, dict)
    return True


def validate(payload, spec):
    """Run the four ordered payload passes and return the effective values."""
    # Rung 27: required fields.
    for fld in spec:
        if fld["required"] and not _present(payload, fld["name"]):
            raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                           "%s is required" % fld["name"])
    # Rung 28: declared types.
    for fld in spec:
        name = fld["name"]
        if not _present(payload, name):
            continue
        if not _type_ok(payload[name], fld["type"]):
            raise ApiError("ERR_FIELD_TYPE_INVALID",
                           "%s must be of type %s" % (name, fld["type"]))
    # Rung 29: enumerations.
    for fld in spec:
        name = fld["name"]
        if fld["enum"] is None or not _present(payload, name):
            continue
        if payload[name] not in fld["enum"]:
            raise ApiError("ERR_ENUM_VALUE_INVALID",
                           "%s must be one of %s" % (name, ", ".join(map(str, fld["enum"]))))
    # Rung 30: numeric / bounded ranges.
    for fld in spec:
        name = fld["name"]
        if not _present(payload, name):
            continue
        value = payload[name]
        if fld["min"] is not None and value < fld["min"]:
            raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                           "%s must be at least %s" % (name, fld["min"]))
        if fld["max"] is not None and value > fld["max"]:
            raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                           "%s must be at most %s" % (name, fld["max"]))
    out = {}
    for fld in spec:
        name = fld["name"]
        if _present(payload, name):
            out[name] = payload[name]
        elif name in payload and fld["nullable"]:
            out[name] = None
        elif fld["default"] is not None:
            out[name] = fld["default"]
        elif fld["type"] == BOOLEAN and fld["default"] is False:
            out[name] = False
    return out


def check_order_version(payload, order):
    """Rung 32: expected_engineered_order_version OCC guard."""
    expected = payload.get("expected_engineered_order_version")
    if expected != order.get("version"):
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "order version is %s, caller expected %s" % (order.get("version"), expected))


def check_component_version(payload, component):
    """Rung 33: expected_component_version OCC guard."""
    expected = payload.get("expected_component_version")
    if expected != component.get("version"):
        raise ApiError("ERR_STALE_COMPONENT_VERSION",
                       "component version is %s, caller expected %s"
                       % (component.get("version"), expected))
