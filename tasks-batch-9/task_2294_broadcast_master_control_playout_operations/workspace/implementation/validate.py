"""Field shape, range and vocabulary checks (PRD 2.9, ladder rows 8-10)."""
import re
from decimal import Decimal, InvalidOperation

from errors import fail
import timeutil


def F(name, kind, required=False, values=None, minimum=None, maximum=None,
      lt=None, gt=None, min_len=None, max_len=None, pattern=None):
    return {
        "name": name, "kind": kind, "required": required, "values": values,
        "minimum": minimum, "maximum": maximum, "lt": lt, "gt": gt,
        "min_len": min_len, "max_len": max_len, "pattern": pattern,
    }


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def body_of(payload):
    if isinstance(payload, dict):
        return payload
    return {}


def validate(payload, fields):
    """Three ordered passes: required presence, enum literals, then type/range."""
    body = body_of(payload)
    for f in fields:
        if f["required"] and body.get(f["name"]) is None:
            fail("ERR_MISSING_REQUIRED_FIELD", "Field '%s' is required." % f["name"])
    for f in fields:
        v = body.get(f["name"])
        if v is None:
            continue
        kind = f["kind"]
        if kind == "enum":
            if not isinstance(v, str) or v not in f["values"]:
                fail("ERR_INVALID_ENUM_VALUE", "Field '%s' carries an unknown literal." % f["name"])
        elif kind == "enum_array":
            if isinstance(v, list):
                for member in v:
                    if not isinstance(member, str) or member not in f["values"]:
                        fail("ERR_INVALID_ENUM_VALUE",
                             "Field '%s' carries an unknown literal." % f["name"])
        elif kind == "enum_number":
            if not _is_num(v) or not any(abs(float(v) - float(o)) < 1e-9 for o in f["values"]):
                fail("ERR_INVALID_ENUM_VALUE", "Field '%s' carries an unknown literal." % f["name"])
    for f in fields:
        v = body.get(f["name"])
        if v is None:
            continue
        name, kind = f["name"], f["kind"]
        if kind == "int":
            if not _is_int(v):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be an integer." % name)
        elif kind == "num":
            if not _is_num(v):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be a number." % name)
        elif kind == "lkfs":
            if not _is_num(v):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be a number." % name)
            try:
                exponent = Decimal(str(v)).normalize().as_tuple().exponent
            except InvalidOperation:
                exponent = 0
            if isinstance(exponent, int) and exponent < -1:
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' carries at most one decimal place." % name)
        elif kind == "bool":
            if not isinstance(v, bool):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be a boolean." % name)
        elif kind == "str":
            if not isinstance(v, str):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be a string." % name)
        elif kind == "ts":
            if not isinstance(v, str) or not timeutil.is_timestamp(v):
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be an RFC 3339 UTC timestamp ending in Z." % name)
        elif kind == "array":
            if not isinstance(v, list):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be an array." % name)
        elif kind == "enum_array":
            if not isinstance(v, list):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be an array." % name)
        elif kind == "object":
            if not isinstance(v, dict):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' must be an object." % name)
        if kind in ("int", "num", "lkfs", "enum_number"):
            if f["minimum"] is not None and v < f["minimum"]:
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be at least %s." % (name, f["minimum"]))
            if f["maximum"] is not None and v > f["maximum"]:
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must not exceed %s." % (name, f["maximum"]))
            if f["lt"] is not None and not v < f["lt"]:
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be below %s." % (name, f["lt"]))
            if f["gt"] is not None and not v > f["gt"]:
                fail("ERR_INVALID_FIELD_VALUE",
                     "Field '%s' must be greater than %s." % (name, f["gt"]))
        if kind == "str" and isinstance(v, str):
            if f["min_len"] is not None and len(v) < f["min_len"]:
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is too short." % name)
            if f["max_len"] is not None and len(v) > f["max_len"]:
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is too long." % name)
            if f["pattern"] is not None and not re.match(f["pattern"], v):
                fail("ERR_INVALID_FIELD_VALUE", "Field '%s' is malformed." % name)
    return body


def require(body, name):
    if body.get(name) is None:
        fail("ERR_MISSING_REQUIRED_FIELD", "Field '%s' is required." % name)
    return body[name]


def enum_filter(name, vocabulary):
    """A query filter over an enum-typed field.

    PRD 2.9: every enum-typed field must carry one of the exact literals,
    matched case-sensitively, and anything else yields ERR_INVALID_ENUM_VALUE.
    """
    from flask import request
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in vocabulary:
        fail("ERR_INVALID_ENUM_VALUE",
             "%s '%s' is not one of the declared literals." % (name, value))
    return value
