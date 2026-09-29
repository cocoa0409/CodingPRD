"""Body / query validation in the pinned ladder order (PRD 2.9 priorities 5-9)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
from errors import fail


# ------------------------------------------------------------- primitives ---

def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool")
    return Decimal(str(value))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ----------------------------------------------------------- field specs ----

def fstr(name, required=True, minlen=None, maxlen=None):
    return {"name": name, "kind": "str", "required": required,
            "minlen": minlen, "maxlen": maxlen}


def fint(name, required=True, lo=None, hi=None, xlo=None):
    return {"name": name, "kind": "int", "required": required,
            "lo": lo, "hi": hi, "xlo": xlo}


def fnum(name, required=True, lo=None, hi=None, xlo=None):
    return {"name": name, "kind": "num", "required": required,
            "lo": lo, "hi": hi, "xlo": xlo}


def fbool(name, required=True):
    return {"name": name, "kind": "bool", "required": required}


def fenum(name, values, required=True):
    return {"name": name, "kind": "enum", "required": required, "values": values}


def farr(name, required=True, minlen=None, maxlen=None):
    return {"name": name, "kind": "array", "required": required,
            "minlen": minlen, "maxlen": maxlen}


def fdate(name, required=True, form="instant"):
    return {"name": name, "kind": "date", "required": required, "form": form}


# ----------------------------------------------------------------- body -----

def body():
    """Parse the JSON body; a missing body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        fail("ERR_INVALID_REQUEST_BODY", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST_BODY", "Request body must be a JSON object.")
    return data


def _type_ok(spec, value):
    kind = spec["kind"]
    if kind == "str" or kind == "enum" or kind == "date":
        return isinstance(value, str)
    if kind == "int":
        return is_int(value)
    if kind == "num":
        return is_num(value)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    return True


def validate(data, specs):
    """Run priority 5, then 6, then 7, then 9 across the whole spec list."""
    # Priority 5 — presence and declared JSON type (plus string lengths).
    for spec in specs:
        name = spec["name"]
        present = name in data and data[name] is not None
        if not present:
            if spec["required"]:
                fail("ERR_INVALID_REQUEST_BODY", "Field '%s' is required." % name)
            continue
        value = data[name]
        if not _type_ok(spec, value):
            fail("ERR_INVALID_REQUEST_BODY",
                 "Field '%s' has the wrong JSON type." % name)
        if spec["kind"] == "str":
            if spec.get("minlen") is not None and len(value) < spec["minlen"]:
                fail("ERR_INVALID_REQUEST_BODY", "Field '%s' is too short." % name)
            if spec.get("maxlen") is not None and len(value) > spec["maxlen"]:
                fail("ERR_INVALID_REQUEST_BODY", "Field '%s' is too long." % name)

    # Priority 6 — enum membership.
    for spec in specs:
        name = spec["name"]
        if spec["kind"] != "enum":
            continue
        if name in data and data[name] is not None:
            if data[name] not in spec["values"]:
                fail("ERR_INVALID_ENUM_VALUE",
                     "Field '%s' carries an unsupported value." % name)

    # Priority 7 — numeric domains and declared array sizes.
    for spec in specs:
        name = spec["name"]
        if name not in data or data[name] is None:
            continue
        value = data[name]
        if spec["kind"] in ("int", "num"):
            num = dec(value)
            if spec.get("xlo") is not None and not num > dec(spec["xlo"]):
                fail("ERR_FIELD_OUT_OF_RANGE", "Field '%s' is out of range." % name)
            if spec.get("lo") is not None and num < dec(spec["lo"]):
                fail("ERR_FIELD_OUT_OF_RANGE", "Field '%s' is out of range." % name)
            if spec.get("hi") is not None and num > dec(spec["hi"]):
                fail("ERR_FIELD_OUT_OF_RANGE", "Field '%s' is out of range." % name)
        elif spec["kind"] == "array":
            if spec.get("minlen") is not None and len(value) < spec["minlen"]:
                fail("ERR_FIELD_OUT_OF_RANGE", "Field '%s' has too few entries." % name)
            if spec.get("maxlen") is not None and len(value) > spec["maxlen"]:
                fail("ERR_FIELD_OUT_OF_RANGE", "Field '%s' has too many entries." % name)

    # Priority 9 — date / month parsing.
    parsed = {}
    for spec in specs:
        name = spec["name"]
        if spec["kind"] != "date":
            continue
        if name not in data or data[name] is None:
            continue
        if spec["form"] == "month":
            got = clock.parse_month(data[name])
        else:
            got = clock.parse_instant(data[name])
        if got is None:
            fail("ERR_INVALID_DATE_FORMAT",
                 "Field '%s' is not a valid date value." % name)
        parsed[name] = got
    return parsed


# ------------------------------------------------------------ pagination ----

def pagination():
    """Priority 8."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _as_int(raw)
        if limit is None or limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer from 1 to 100.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _as_int(raw)
        if offset is None or offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
    return limit, offset


def _as_int(raw):
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    neg = raw.startswith("-")
    digits = raw[1:] if (neg or raw.startswith("+")) else raw
    if not digits.isdigit():
        return None
    return int(raw)


def window(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def filter_bool(rows, field, raw):
    if raw is None:
        return rows
    want = raw.lower() in ("true", "1", "yes")
    return [r for r in rows if bool(r.get(field)) == want]
